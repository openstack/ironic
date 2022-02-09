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

import socket

from ironic_lib import utils as il_utils
from oslo_concurrency import processutils
from oslo_service import service
from oslo_service import wsgi

from ironic.api import app
from ironic.common import exception
from ironic.common.i18n import _
from ironic.conf import CONF


_MAX_DEFAULT_WORKERS = 4


class WSGIService(service.ServiceBase):
    """Provides ability to launch ironic API from wsgi app."""

    def __init__(self, name, use_ssl=False):
        """Initialize, but do not start the WSGI server.

        :param name: The name of the WSGI server given to the loader.
        :param use_ssl: Wraps the socket in an SSL context if True.
        :returns: None
        """
        self.name = name
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

        if CONF.api.unix_socket:
            il_utils.unlink_without_raise(CONF.api.unix_socket)
            self.server = wsgi.Server(CONF, name, self.app,
                                      socket_family=socket.AF_UNIX,
                                      socket_file=CONF.api.unix_socket,
                                      socket_mode=CONF.api.unix_socket_mode,
                                      use_ssl=use_ssl)
        else:
            self.server = wsgi.Server(CONF, name, self.app,
                                      host=CONF.api.host_ip,
                                      port=CONF.api.port,
                                      use_ssl=use_ssl)

    def start(self):
        """Start serving this service using loaded configuration.

        :returns: None
        """
        self.server.start()

    def stop(self):
        """Stop serving this API.

        :returns: None
        """
        self.server.stop()
        if CONF.api.unix_socket:
            il_utils.unlink_without_raise(CONF.unix_socket)

    def wait(self):
        """Wait for the service to stop serving this API.

        :returns: None
        """
        self.server.wait()

    def reset(self):
        """Reset server greenpool size to default.

        :returns: None
        """
        self.server.reset()
