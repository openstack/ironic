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

from oslo_config import cfg
from oslo_service import service
from oslo_service import wsgi

from ironic.common import utils

CONF = cfg.CONF


class WSGIService(service.ServiceBase):

    def __init__(self, name, app, conf):
        """Initialize, but do not start the WSGI server.

        :param name: The name of the WSGI server given to the loader.
        :param app: WSGI application to run.
        :param conf: Object to load configuration from.
        :returns: None
        """
        self.name = name
        self._conf = conf
        if conf.unix_socket:
            utils.unlink_without_raise(conf.unix_socket)
            self.server = wsgi.Server(CONF, name, app,
                                      socket_family=socket.AF_UNIX,
                                      socket_file=conf.unix_socket,
                                      socket_mode=conf.unix_socket_mode,
                                      use_ssl=conf.use_ssl)
        else:
            self.server = wsgi.Server(CONF, name, app,
                                      host=conf.host_ip,
                                      port=conf.port,
                                      use_ssl=conf.use_ssl)

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
        if self._conf.unix_socket:
            utils.unlink_without_raise(self._conf.unix_socket)

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
