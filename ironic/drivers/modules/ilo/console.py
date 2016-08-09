# Copyright 2015 Hewlett-Packard Development Company, L.P.
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
"""
iLO Deploy Driver(s) and supporting methods.
"""

from ironic_lib import metrics_utils

from ironic.common import exception
from ironic.common.i18n import _
from ironic.drivers.modules.ilo import common as ilo_common
from ironic.drivers.modules import ipmitool

METRICS = metrics_utils.get_metrics_logger(__name__)


class IloConsoleInterface(ipmitool.IPMIShellinaboxConsole):
    """A ConsoleInterface that uses ipmitool and shellinabox."""

    def get_properties(self):
        props = ilo_common.REQUIRED_PROPERTIES.copy()
        props.update(ilo_common.CONSOLE_PROPERTIES)
        return props

    @METRICS.timer('IloConsoleInterface.validate')
    def validate(self, task):
        """Validate the Node console info.

        :param task: a task from TaskManager.
        :raises: InvalidParameterValue
        :raises: MissingParameterValue when a required parameter is missing

        """
        node = task.node
        driver_info_dict = ilo_common.parse_driver_info(node)
        if 'console_port' not in driver_info_dict:
            raise exception.MissingParameterValue(_(
                "Missing 'console_port' parameter in node's driver_info."))

        ilo_common.update_ipmi_properties(task)
        super(IloConsoleInterface, self).validate(task)
