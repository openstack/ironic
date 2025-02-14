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


class BaseConsoleContainer(object, metaclass=abc.ABCMeta):
    """Base class for console container provider APIs."""

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
