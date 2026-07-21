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

"""
Abstract base class for console container providers.
"""

import abc
import socket
import time

from oslo_log import log as logging

from ironic.common import exception
from ironic.conf import CONF
from ironic.console.rfb import auth

LOG = logging.getLogger(__name__)


class BaseConsoleContainer(object, metaclass=abc.ABCMeta):
    """Base class for console container provider APIs."""

    # Provider name used in error messages, to be set by subclasses
    @property
    @abc.abstractmethod
    def provider_name(self) -> str:
        """Provider name used in error messages"""
        ...

    @abc.abstractmethod
    def start_container(self, task, app_name, app_info):
        """Start a console container for a node.

        Calling this will block until a consumable container host and port can
        be returned.

        :param task: A TaskManager instance.
        :param app_name: Name of app to run in the container
        :param app_info: Dict of app-specific info
        :returns: Tuple of host IP address and published port
        :raises: ConsoleContainerError
        """

    @abc.abstractmethod
    def stop_container(self, task):
        """Stop a console container for a node.

        Any existing running container for this node will be stopped.

        :param task: A TaskManager instance.
        :raises: ConsoleContainerError
        """

    @abc.abstractmethod
    def stop_all_containers(self):
        """Stops all running console containers

        This is run on conductor startup and graceful shutdown to ensure
        no console containers are running.
        :raises: ConsoleContainerError
        """

    def _wait_for_listen(self, host, port):
        """Blocks until VNC port is returning data

        :param host: Host IP address to connect to
        :param port: TCP port to connect to
        :raises: ConsoleContainerError when no RFB data is returned within
            [vnc]wait_for_ready_timeout seconds
        """
        for i in range(CONF.vnc.wait_for_ready_timeout):
            try:
                # open a TCP socket using host and port and request 12 bytes of
                # data. This will either fail to connect, or return zero bytes
                # until the container is listening on the port.
                LOG.debug("Attempt %s to connect to %s:%s", i, host, port)
                with socket.create_connection((host, port), timeout=1) as sock:
                    b = sock.recv(auth.VERSION_LENGTH)
                    if len(b) == auth.VERSION_LENGTH:
                        return
                    LOG.debug("Expected %s bytes, got %s",
                              auth.VERSION_LENGTH, len(b))
            except Exception:
                pass
            time.sleep(1)
        reason = f"RFB data not returned by {host}:{port}"
        raise exception.ConsoleContainerError(
            provider=self.provider_name, reason=reason)
