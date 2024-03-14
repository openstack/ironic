# Copyright 2022 FUJITSU LIMITED
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
Vendor interface of iRMC driver
"""

from ironic.common import exception
from ironic.common.i18n import _
from ironic.drivers import base
from ironic.drivers.modules.irmc import common as irmc_common


class IRMCVendorPassthru(base.VendorInterface):
    def get_properties(self):
        """Return the properties of the interface.

        :returns: Dictionary of <property name>:<property description> entries.
        """
        return irmc_common.COMMON_PROPERTIES

    def validate(self, task, method=None, **kwargs):
        """Validate vendor-specific actions.

        This method validates whether the 'driver_info' property of the
        supplied node contains the required information for this driver.

        :param task: An instance of TaskManager.
        :param method: Name of vendor passthru method
        :raises: InvalidParameterValue if invalid value is contained
            in the 'driver_info' property.
        :raises: MissingParameterValue if some mandatory key is missing
            in the 'driver_info' property.
        """
        irmc_common.parse_driver_info(task.node)

    @base.passthru(['POST'],
                   async_call=True,
                   description='Connect to iRMC and fetch iRMC firmware '
                   'version and, if firmware version has not been cached '
                   'in or actual firmware version is different from one in '
                   'driver_internal_info/irmc_fw_version, store firmware '
                   'version in driver_internal_info/irmc_fw_version.',
                   attach=False,
                   require_exclusive_lock=False)
    def cache_irmc_firmware_version(self, task, **kwargs):
        """Fetch and save iRMC firmware version.

        This method connects to iRMC and fetch iRMC firmware version.
        If fetched firmware version is not cached in or is different from
        one in driver_internal_info/irmc_fw_version, store fetched version
        in driver_internal_info/irmc_fw_version.

        :param task: An instance of TaskManager.
        :raises: IRMCOperationError if some error occurs
        """
        try:
            irmc_common.set_irmc_version(task)
        except (exception.IRMCOperationError,
                exception.InvalidParameterValue,
                exception.MissingParameterValue,
                exception.NodeLocked) as e:
            raise exception.IRMCOperationError(
                operation=_('caching firmware version'), error=e)
