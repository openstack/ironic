#   Copyright 2025 Red Hat, Inc.
#
# Licensed under the Apache License, Version 2.0 (the "License"); you may
# not use this file except in compliance with the License. You may obtain
# a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
# WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
# License for the specific language governing permissions and limitations
# under the License.

import os

from oslo_config import cfg
from oslo_log import log
from oslo_service import service

from ironic.common import exception
from ironic.console.securityproxy import rfb
from ironic.console import websocketproxy

LOG = log.getLogger(__name__)
CONF = cfg.CONF


class NoVNCProxyService(service.Service):

    def __init__(self):
        super().__init__()
        self._started = False
        self._failure = None

    def start(self):
        self._failure = None
        self._started = False
        super().start()
        try:
            self._real_start()
        except Exception as exc:
            self._failure = f"{exc.__class__.__name__}: {exc}"
            raise
        else:
            self._started = True

    def _real_start(self):
        kwargs = {
            'listen_host': CONF.vnc.host_ip,
            'listen_port': CONF.vnc.port,
            'source_is_ipv6': bool(CONF.my_ipv6),
            'record': CONF.vnc.novnc_record,
            'web': CONF.vnc.novnc_web,
            'file_only': True,
            'RequestHandlerClass': websocketproxy.IronicProxyRequestHandler,
            'security_proxy': rfb.RFBSecurityProxy(),
        }
        if CONF.vnc.enable_ssl:
            kwargs.update({
                'cert': CONF.vnc.ssl_cert_file,
                'key': CONF.vnc.ssl_key_file,
                'ssl_only': CONF.vnc.enable_ssl,
                'ssl_ciphers': CONF.vnc.ssl_ciphers,
                'ssl_minimum_version': CONF.vnc.ssl_minimum_version,
            })

        # Check to see if tty html/js/css files are present
        if CONF.vnc.novnc_web and not os.path.exists(CONF.vnc.novnc_web):
            raise exception.ConfigInvalid(
                "Can not find html/js files at %s." % CONF.vnc.novnc_web)

        # Create and start the IronicWebSockets proxy
        websocketproxy.IronicWebSocketProxy(**kwargs).start_server()
