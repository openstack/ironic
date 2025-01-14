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

"""Multicast DNS implementation for API discovery.

This implementation follows RFC 6763 as clarified by the API SIG guideline
https://review.opendev.org/651222.
"""

import collections
import logging
import socket
import time
from urllib import parse as urlparse

import zeroconf

from ironic.common import exception
from ironic.common.i18n import _
from ironic.conf import CONF


LOG = logging.getLogger(__name__)

_MDNS_DOMAIN = '_openstack._tcp.local.'
_endpoint = collections.namedtuple('Endpoint',
                                   ['addresses', 'hostname', 'port', 'params'])


class Zeroconf(object):
    """Multicast DNS implementation client and server.

    Uses threading internally, so there is no start method. It starts
    automatically on creation.

    .. warning::
        The underlying library does not yet support IPv6.
    """

    def __init__(self):
        """Initialize and start the mDNS server."""
        interfaces = (CONF.mdns.interfaces if CONF.mdns.interfaces
                      else zeroconf.InterfaceChoice.All)
        # If interfaces are set, let zeroconf auto-detect the version
        ip_version = None if CONF.mdns.interfaces else zeroconf.IPVersion.All
        self._zc = zeroconf.Zeroconf(interfaces=interfaces,
                                     ip_version=ip_version)
        self._registered = []

    def register_service(self, service_type, endpoint, params=None):
        """Register a service.

        This call announces the new services via multicast and instructs the
        built-in server to respond to queries about it.

        :param service_type: OpenStack service type, e.g. "baremetal".
        :param endpoint: full endpoint to reach the service.
        :param params: optional properties as a dictionary.
        :raises: :exc:`.ServiceRegistrationFailure` if the service cannot be
            registered, e.g. because of conflicts.
        """
        parsed = _parse_endpoint(endpoint, service_type)

        all_params = CONF.mdns.params.copy()
        if params:
            all_params.update(params)
        all_params.update(parsed.params)

        properties = {
            (key.encode('utf-8') if isinstance(key, str) else key):
            (value.encode('utf-8') if isinstance(value, str) else value)
            for key, value in all_params.items()
        }

        # TODO(dtantsur): allow overriding TTL values via configuration
        info = zeroconf.ServiceInfo(_MDNS_DOMAIN,
                                    '%s.%s' % (service_type, _MDNS_DOMAIN),
                                    addresses=parsed.addresses,
                                    port=parsed.port,
                                    properties=properties,
                                    server=parsed.hostname)

        LOG.debug('Registering %s via mDNS', info)
        # Work around a potential race condition in the registration code:
        # https://github.com/jstasiak/python-zeroconf/issues/163
        delay = 0.1
        try:
            for attempt in range(CONF.mdns.registration_attempts):
                try:
                    self._zc.register_service(info)
                except zeroconf.NonUniqueNameException:
                    LOG.debug('Could not register %s - conflict', info)
                    if attempt == CONF.mdns.registration_attempts - 1:
                        raise
                    # reset the cache to purge learned records and retry
                    self._zc.cache = zeroconf.DNSCache()
                    time.sleep(delay)
                    delay *= 2
                else:
                    break
        except zeroconf.Error as exc:
            raise exception.ServiceRegistrationFailure(
                service=service_type, error=exc)

        self._registered.append(info)

    def close(self):
        """Shut down mDNS and unregister services.

        .. note::
            If another server is running for the same services, it will
            re-register them immediately.
        """
        for info in self._registered:
            try:
                self._zc.unregister_service(info)
            except Exception:
                LOG.exception('Cound not unregister mDNS service %s', info)
        self._zc.close()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()


def _parse_endpoint(endpoint, service_type=None):
    params = {}
    url = urlparse.urlparse(endpoint)
    port = url.port

    if port is None:
        if url.scheme == 'https':
            port = 443
        else:
            port = 80

    addresses = []
    hostname = url.hostname
    try:
        infos = socket.getaddrinfo(hostname, port, 0, socket.IPPROTO_TCP)
    except socket.error as exc:
        raise exception.ServiceRegistrationFailure(
            service=service_type,
            error=_('Could not resolve hostname %(host)s: %(exc)s') %
            {'host': hostname, 'exc': exc})

    for info in infos:
        ip = info[4][0]
        if ip == hostname:
            # we need a host name for the service record. if what we have in
            # the catalog is an IP address, use the local hostname instead
            hostname = None
        # zeroconf requires addresses in network format
        ip = socket.inet_pton(info[0], ip)
        if ip not in addresses:
            addresses.append(ip)
    if not addresses:
        raise exception.ServiceRegistrationFailure(
            service=service_type,
            error=_('No suitable addresses found for %s') % url.hostname)

    # avoid storing information that can be derived from existing data
    if url.path not in ('', '/'):
        params['path'] = url.path

    if (not (port == 80 and url.scheme == 'http')
            and not (port == 443 and url.scheme == 'https')):
        params['protocol'] = url.scheme

    # zeroconf is pretty picky about having the trailing dot
    if hostname is not None and not hostname.endswith('.'):
        hostname += '.'

    return _endpoint(addresses, hostname, port, params)
