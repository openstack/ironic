# Copyright (c) 2012 OpenStack Foundation
# All Rights Reserved.
#
#    Licensed under the Apache License, Version 2.0 (the "License"); you may
#    not use this file except in compliance with the License. You may obtain
#    a copy of the License at
#
#         http://www.apache.org/licenses/LICENSE-2.0
#
#    Unless required by applicable law or agreed to in writing, software
#    distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
#    WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
#    License for the specific language governing permissions and limitations
#    under the License.

'''
Websocket proxy that is compatible with OpenStack Ironic.
Leverages websockify.py by Joel Martin
'''

from http import HTTPStatus
import os
import socket
from urllib import parse as urlparse

from oslo_log import log
from oslo_utils import encodeutils
import websockify
from websockify import websockifyserver

from ironic.common import context
from ironic.common import exception
from ironic.common.i18n import _
from ironic.common import vnc
import ironic.conf
from ironic import objects

LOG = log.getLogger(__name__)

CONF = ironic.conf.CONF


class TenantSock(object):
    """A socket wrapper for communicating with the tenant.

    This class provides a socket-like interface to the internal
    websockify send/receive queue for the client connection to
    the tenant user. It is used with the security proxy classes.
    """

    def __init__(self, reqhandler):
        self.reqhandler = reqhandler
        self.queue = []

    def recv(self, cnt):
        # NB(sross): it's ok to block here because we know
        #            exactly the sequence of data arriving
        while len(self.queue) < cnt:
            # new_frames looks like ['abc', 'def']
            new_frames, closed = self.reqhandler.recv_frames()
            # flatten frames onto queue
            for frame in new_frames:
                self.queue.extend(
                    [bytes(chr(c), 'ascii') for c in frame])

            if closed:
                break

        popped = self.queue[0:cnt]
        del self.queue[0:cnt]
        return b''.join(popped)

    def sendall(self, data):
        self.reqhandler.send_frames([encodeutils.safe_encode(data)])

    def finish_up(self):
        self.reqhandler.send_frames([b''.join(self.queue)])

    def close(self):
        self.finish_up()
        self.reqhandler.send_close()


class IronicProxyRequestHandler(websockify.ProxyRequestHandler):

    def __init__(self, *args, **kwargs):
        self._compute_rpcapi = None
        websockify.ProxyRequestHandler.__init__(self, *args, **kwargs)

    def _get_node(self, ctxt, token, node_uuid):
        """Get the node and validate the token."""
        try:
            node = objects.Node.get_by_uuid(ctxt, node_uuid)
            vnc.novnc_validate(node, token)
        except exception.NodeNotFound:
            raise exception.NotAuthorized()
        return node

    def _close_connection(self, tsock, host, port):
        """Takes target socket and close the connection.

        """
        try:
            tsock.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass
        finally:
            if tsock.fileno() != -1:
                tsock.close()
                self.vmsg(_("%(host)s:%(port)s: "
                            "Websocket client or target closed") %
                          {'host': host, 'port': port})

    def new_websocket_client(self):
        """Called after a new WebSocket connection has been established."""
        # The ironic expected behavior is to have token
        # passed to the method GET of the request
        qs = urlparse.parse_qs(urlparse.urlparse(self.path).query)
        token = qs.get('token', ['']).pop()
        node_uuid = qs.get('node', ['']).pop()

        ctxt = context.get_admin_context()
        node = self._get_node(ctxt, token, node_uuid)

        # Verify Origin
        expected_origin_hostname = self.headers.get('Host')
        if ':' in expected_origin_hostname:
            e = expected_origin_hostname
            if '[' in e and ']' in e:
                expected_origin_hostname = e.split(']')[0][1:]
            else:
                expected_origin_hostname = e.split(':')[0]
        expected_origin_hostnames = CONF.cors.allowed_origin or []
        expected_origin_hostnames.append(expected_origin_hostname)
        origin_url = self.headers.get('Origin')
        # missing origin header indicates non-browser client which is OK
        if origin_url is not None:
            origin = urlparse.urlparse(origin_url)
            origin_hostname = origin.hostname
            origin_scheme = origin.scheme
            # If the console connection was forwarded by a proxy (example:
            # haproxy), the original protocol could be contained in the
            # X-Forwarded-Proto header instead of the Origin header. Prefer the
            # forwarded protocol if it is present.
            forwarded_proto = self.headers.get('X-Forwarded-Proto')
            if forwarded_proto is not None:
                origin_scheme = forwarded_proto
            if origin_hostname == '' or origin_scheme == '':
                detail = _("Origin header not valid.")
                raise exception.NotAuthorized(detail)
            if origin_hostname not in expected_origin_hostnames:
                detail = _("Origin header does not match this host.")
                raise exception.NotAuthorized(detail)

        host = node.driver_internal_info.get('vnc_host')
        port = node.driver_internal_info.get('vnc_port')

        # Connect to the target
        self.msg(_("connecting to: %(host)s:%(port)s") % {'host': host,
                                                          'port': port})
        tsock = self.socket(host, port, connect=True)

        if self.server.security_proxy is not None:
            tenant_sock = TenantSock(self)

            try:
                tsock = self.server.security_proxy.connect(tenant_sock, tsock)
            except exception.SecurityProxyNegotiationFailed:
                LOG.exception("Unable to perform security proxying, shutting "
                              "down connection")
                tenant_sock.close()
                tsock.shutdown(socket.SHUT_RDWR)
                tsock.close()
                raise

            tenant_sock.finish_up()

        # Start proxying
        try:
            self.do_proxy(tsock)
        except Exception:
            self._close_connection(tsock, host, port)
            raise

    def socket(self, *args, **kwargs):
        return websockifyserver.WebSockifyServer.socket(*args, **kwargs)

    def send_head(self):
        # This code is copied from this example patch:
        # https://bugs.python.org/issue32084#msg306545
        path = self.translate_path(self.path)
        if os.path.isdir(path):
            parts = urlparse.urlsplit(self.path)
            if not parts.path.endswith('/'):
                # Browsers interpret "Location: //uri" as an absolute URI
                # like "http://URI"
                if self.path.startswith('//'):
                    self.send_error(HTTPStatus.BAD_REQUEST,
                                    "URI must not start with //")
                    return None

        return super(IronicProxyRequestHandler, self).send_head()


class IronicWebSocketProxy(websockify.WebSocketProxy):
    def __init__(self, *args, **kwargs):
        """Create a new web socket proxy

        :param security_proxy: instance of
            ironic.console.securityproxy.base.SecurityProxy

        Optionally using the @security_proxy instance to negotiate security
        layer with the compute node.
        """
        self.security_proxy = kwargs.pop('security_proxy', None)

        # If 'default' was specified as the ssl_minimum_version, we leave
        # ssl_options unset to default to the underlying system defaults.
        # We do this to avoid using websockify's behaviour for 'default'
        # in select_ssl_version(), which hardcodes the versions to be
        # quite relaxed and prevents us from using system crypto policies.
        ssl_min_version = kwargs.pop('ssl_minimum_version', None)
        if ssl_min_version and ssl_min_version != 'default':
            options = websockify.websocketproxy.select_ssl_version(
                ssl_min_version)
            kwargs['ssl_options'] = options

        super(IronicWebSocketProxy, self).__init__(*args, **kwargs)

    @staticmethod
    def get_logger():
        return LOG

    def terminate(self):
        """Override WebSockifyServer terminate

        ``WebSocifyServer.Terminate`` exception is not handled by
        oslo_service, so raise ``SystemExit`` instead.
        """
        if not self.terminating:
            self.terminating = True
            e = SystemExit()
            e.code = 1
            raise e
