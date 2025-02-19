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

from oslo_log import log as logging

from ironic.common import metrics_utils
from ironic.conductor import periodics
from ironic import conf
from ironic.drivers.modules import graphical_console
from ironic.drivers.modules.redfish import utils as redfish_utils

LOG = logging.getLogger(__name__)
CONF = conf.CONF

METRICS = metrics_utils.get_metrics_logger(__name__)


class RedfishGraphicalConsole(graphical_console.GraphicalConsole):

    def get_app_name(self):
        return 'redfish-graphical'

    def get_properties(self):
        """Return the properties of the interface.

        :returns: dictionary of <property name>:<property description> entries.
        """
        return redfish_utils.COMMON_PROPERTIES.copy()

    def validate(self, task):
        """Validates the driver information needed by the redfish driver.

        :param task: a TaskManager instance containing the node to act on.
        :raises: InvalidParameterValue on malformed parameter(s)
        :raises: MissingParameterValue on missing parameter(s)
        """
        node = task.node
        redfish_utils.parse_driver_info(node)

    def get_app_info(self, task):
        """Information required by the app to connect to the console

        For redfish based consoles the app info will be the parsed driver
        info.

        :returns: dict containing parsed driver info
        """
        return redfish_utils.parse_driver_info(task.node)

    @METRICS.timer('RedfishGraphicalConsole._expire_console_sessions')
    @periodics.node_periodic(
        purpose='checking active console sessions',
        spacing=CONF.vnc.expire_console_session_interval,
        filters={'console_enabled': True},
        predicate_extra_fields=['console_interface', 'driver_internal_info'],
        predicate=lambda n: (
            'redfish-graphical' == n.console_interface
                and n.driver_internal_info.get('novnc_secret_token')
        ),
    )
    def _expire_redfish_console_sessions(self, task, manager, context):
        """Periodic task to close expired console sessions"""
        self._expire_console_sessions(task)
