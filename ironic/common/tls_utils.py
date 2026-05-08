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

"""Shared TLS utilities for Ironic.

This module consolidates TLS-related constants, adapters, and helpers
that were previously duplicated across image_service, agent_client,
and wsgi_service.
"""

import ssl

from requests import adapters as req_adapters

from ironic.common.i18n import _


TLS_VERSION_MAP = {
    '1.2': ssl.TLSVersion.TLSv1_2,
    '1.3': ssl.TLSVersion.TLSv1_3,
}


def check_tls_version_supported(version_str):
    """Validate that the requested TLS version is available.

    Checks both compile-time flags and runtime crypto policy
    to ensure the configured TLS version can actually be used.
    Raises RuntimeError with a clear message at startup rather
    than letting the service fail later with an opaque SSL
    error.
    """
    version = TLS_VERSION_MAP[version_str]

    if not getattr(ssl, f'HAS_{version.name}', False):
        raise RuntimeError(
            _("TLS %(ver)s is not supported by the "
              "installed version of OpenSSL "
              "(ssl.HAS_%(attr)s is not set).")
            % {'ver': version_str, 'attr': version.name}
        )

    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    max_ver = ctx.maximum_version
    if (max_ver != ssl.TLSVersion.MAXIMUM_SUPPORTED
            and version > max_ver):
        raise RuntimeError(
            _("TLS %(ver)s exceeds the maximum TLS "
              "version allowed by the system crypto "
              "policy.")
            % {'ver': version_str}
        )


class TLSHTTPAdapter(req_adapters.HTTPAdapter):
    """HTTPS adapter with configurable TLS settings."""

    def __init__(self, ssl_context=None, **kwargs):
        self._ssl_context = ssl_context
        super().__init__(**kwargs)

    def init_poolmanager(self, *args, **kwargs):
        if self._ssl_context:
            kwargs['ssl_context'] = self._ssl_context
        super().init_poolmanager(*args, **kwargs)


def build_ssl_context(tls_minimum_version=None, tls_ciphers=None):
    """Create an ssl.SSLContext with the given TLS constraints.

    :param tls_minimum_version: Minimum TLS version string
        (e.g. '1.2', '1.3') or None.
    :param tls_ciphers: OpenSSL cipher string or None.
    :returns: A configured ssl.SSLContext, or None if both
        params are falsy.
    """
    if not tls_minimum_version and not tls_ciphers:
        return None

    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    # Verification is handled separately via the requests
    # verify parameter; default to permissive here so that
    # the caller's verify setting remains the single source
    # of truth.
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE

    if tls_minimum_version:
        ctx.minimum_version = TLS_VERSION_MAP[tls_minimum_version]

    if tls_ciphers:
        ctx.set_ciphers(tls_ciphers)

    return ctx
