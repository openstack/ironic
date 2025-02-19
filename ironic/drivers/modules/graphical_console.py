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

import abc

from oslo_log import log as logging
from oslo_utils import timeutils

from ironic.common import console_factory
from ironic.common import metrics_utils
from ironic.common import vnc as vnc_utils
from ironic.drivers import base

LOG = logging.getLogger(__name__)

METRICS = metrics_utils.get_metrics_logger(__name__)


class GraphicalConsole(base.ConsoleInterface):

    @abc.abstractmethod
    def get_app_name(self):
        """Get the name of the app passed to the console container.

        A single console container image is expected to support all known
        graphical consoles and each implementation is referred to as an app.
        Each graphical console driver will specify what app to load in the
        container.

        :returns: String representing the app name to load in the console
                  container
        """

    def get_app_info(self, task):
        """Information required by the app to connect to the console

        :returns: dict containing app-specific values
        """
        return {}

    @METRICS.timer('GraphicalConsole.start_console')
    def start_console(self, task):
        node = task.node

        provider = console_factory.ConsoleContainerFactory().provider
        host, port = provider.start_container(
            task, self.get_app_name(), self.get_app_info(task))

        node.set_driver_internal_info('vnc_host', host)
        node.set_driver_internal_info('vnc_port', port)
        node.console_enabled = True
        vnc_utils.novnc_authorize(node)

        node.save()

    @METRICS.timer('GraphicalConsole.stop_console')
    def stop_console(self, task):
        node = task.node

        provider = console_factory.ConsoleContainerFactory().provider
        provider.stop_container(task)

        node.del_driver_internal_info('vnc_port')
        node.del_driver_internal_info('vnc_host')
        node.console_enabled = False
        vnc_utils.novnc_unauthorize(node)

    def get_console(self, task):
        """Get the type and connection information about the console."""
        return vnc_utils.get_console(task.node)

    def _expire_console_sessions(self, task):
        """Expire the session if it is no longer valid.

        This is called by a periodic task.
        :returns: True if the console was stopped
        """
        node = task.node
        LOG.debug('Checking graphical console session for node: %s', node.uuid)
        if vnc_utils.token_valid_until(node) < timeutils.utcnow():
            LOG.info('Graphical console session has expired for %s, closing.',
                     node.uuid)
            self.stop_console(task)
            return True
