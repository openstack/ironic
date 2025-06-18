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
import threading

from cheroot.ssl import builtin as cheroot_ssl
from cheroot import wsgi
from oslo_concurrency import processutils
from oslo_log import log as logging
from oslo_service import service
from oslo_service import sslutils

from ironic.api import app
from ironic.common import exception
from ironic.common.i18n import _
from ironic.common import utils
from ironic.conf import CONF


LOG = logging.getLogger(__name__)
_MAX_DEFAULT_WORKERS = 4


def validate_cert_paths(cert_file, key_file):
    if cert_file and not os.path.exists(cert_file):
        raise RuntimeError(_("Unable to find cert_file: %s") % cert_file)
    if key_file and not os.path.exists(key_file):
        raise RuntimeError(_("Unable to find key_file: %s") % key_file)

    if not cert_file or not key_file:
        raise RuntimeError(_("When running server in SSL mode, you must "
                             "specify a valid cert_file and key_file "
                             "paths in your configuration file"))


class BaseWSGIService(service.ServiceBase):

    def __init__(self, name, app, conf, use_ssl=None):
        """Initialize, but do not start the WSGI server.

        :param name: The name of the WSGI server given to the loader.
        :param app: WSGI application to run.
        :param conf: Object to load configuration from.
        :param use_ssl: Whether to use TLS on the socker.
        :returns: None
        """
        self.name = name
        self._conf = conf
        if use_ssl is None:
            use_ssl = conf.use_ssl

        socket_mode = None
        bind_addr = (conf.host_ip, conf.port)
        if conf.unix_socket:
            utils.unlink_without_raise(conf.unix_socket)
            bind_addr = conf.unix_socket
            socket_mode = conf.unix_socket_mode

        self.server = wsgi.Server(
            bind_addr=bind_addr,
            wsgi_app=app,
            server_name=name)

        if use_ssl:
            cert_file = getattr(conf, "cert_file", None)
            key_file = getattr(conf, "key_file", None)

            if not (cert_file and key_file):
                LOG.warning(
                    "Falling back to deprecated [ssl] group for TLS "
                    "credentials: the global [ssl] configuration block is "
                    "deprecated and will be removed in 2026.1"
                )

                # Register global SSL config options and validate the
                # existence of configured certificate/private key file paths,
                # when in secure mode.
                sslutils.is_enabled(CONF)
                cert_file = CONF.ssl.cert_file
                key_file = CONF.ssl.key_file

            validate_cert_paths(cert_file, key_file)

            self.server.ssl_adapter = cheroot_ssl.BuiltinSSLAdapter(
                certificate=cert_file,
                private_key=key_file,
            )

        self._unix_socket = conf.unix_socket
        self._socket_mode = socket_mode
        self._thread = None

    def start(self):
        """Start serving this service using loaded configuration.

        :returns: None
        """
        self.server.prepare()

        if self._unix_socket and self._socket_mode is not None:
            os.chmod(self._unix_socket, self._socket_mode)

        self._thread = threading.Thread(
            target=self.server.serve,
            daemon=True
        )

        self._thread.start()

    def stop(self):
        """Stop serving this API.

        :returns: None
        """
        if self.server:
            self.server.stop()
            if self._thread:
                self._thread.join(timeout=2)

        if self._unix_socket:
            utils.unlink_without_raise(self._unix_socket)

    def wait(self):
        """Wait for the service to stop serving this API.

        :returns: None
        """
        if self._thread:
            self._thread.join()

    def reset(self):
        """No server greenpools to resize."""
        pass


class WSGIService(BaseWSGIService):
    """Provides ability to launch ironic API from wsgi app."""

    def __init__(self, name, use_ssl=False):
        """Initialize, but do not start the WSGI server.

        :param name: The name of the WSGI server given to the loader.
        :param use_ssl: Wraps the socket in an SSL context if True.
        :returns: None
        """
        self.app = app.VersionSelectorApplication()
        self.workers = (
            CONF.api.api_workers
            # NOTE(dtantsur): each worker takes a substantial amount of memory,
            # so we don't want to end up with dozens of them.
            or min(processutils.get_worker_count(), _MAX_DEFAULT_WORKERS)
        )
        if self.workers and self.workers < 1:
            raise exception.ConfigInvalid(
                _("api_workers value of %d is invalid, "
                  "must be greater than 0.") % self.workers)

        super().__init__(name, self.app, CONF.api, use_ssl=use_ssl)
