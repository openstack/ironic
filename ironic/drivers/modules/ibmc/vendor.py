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
iBMC Vendor Interface
"""

from oslo_log import log
from oslo_utils import importutils

from ironic.common import exception
from ironic.common.i18n import _
from ironic.drivers import base
from ironic.drivers.modules.ibmc import utils

ibmc_client = importutils.try_import('ibmc_client')

LOG = log.getLogger(__name__)


class IBMCVendor(base.VendorInterface):

    # NOTE(TheJulia): Deprecating November 2023 in favor of Redfish
    # and due to a lack of active driver maintenance.
    supported = False

    def __init__(self):
        """Initialize the iBMC vendor interface.

        :raises: DriverLoadError if the driver can't be loaded due to
            missing dependencies
        """
        super(IBMCVendor, self).__init__()
        if not ibmc_client:
            raise exception.DriverLoadError(
                driver='ibmc',
                reason=_('Unable to import the python-ibmcclient library'))

    def validate(self, task, method=None, **kwargs):
        """Validate vendor-specific actions.

        If invalid, raises an exception; otherwise returns None.

        :param task: A task from TaskManager.
        :param method: Method to be validated
        :param kwargs: Info for action.
        :raises: UnsupportedDriverExtension if 'method' can not be mapped to
                 the supported interfaces.
        :raises: InvalidParameterValue if kwargs does not contain 'method'.
        :raises: MissingParameterValue
        """
        utils.parse_driver_info(task.node)

    def get_properties(self):
        """Return the properties of the interface.

        :returns: dictionary of <property name>:<property description> entries.
        """
        return utils.COMMON_PROPERTIES.copy()

    @base.passthru(['GET'], async_call=False,
                   description=_('Returns a dictionary, '
                                 'containing node boot up sequence, '
                                 'in ascending order'))
    @utils.handle_ibmc_exception('get iBMC boot up sequence')
    def boot_up_seq(self, task, **kwargs):
        """List boot type order of the node.

        :param task: A TaskManager instance containing the node to act on.
        :param kwargs: Not used.
        :raises: InvalidParameterValue if kwargs does not contain 'method'.
        :raises: MissingParameterValue
        :raises: IBMCConnectionError when it fails to connect to iBMC
        :raises: IBMCError when iBMC responses an error information
        :returns: A dictionary, containing node boot up sequence,
                in ascending order.
        """
        driver_info = utils.parse_driver_info(task.node)
        with ibmc_client.connect(**driver_info) as conn:
            system = conn.system.get()
            boot_sequence = system.boot_sequence
            return {'boot_up_sequence': boot_sequence}

    @base.passthru(['GET'], async_call=False,
                   description=_('Returns a list of dictionary, every '
                                 'dictionary represents a RAID controller '
                                 'summary info'))
    @utils.handle_ibmc_exception('get iBMC RAID controller summary')
    def get_raid_controller_list(self, task, **kwargs):
        """List RAID controllers summary info of the node.

        :param task: A TaskManager instance containing the node to act on.
        :param kwargs: Not used.
        :raises: IBMCConnectionError when it fails to connect to iBMC
        :raises: IBMCError when iBMC responses an error information
        :returns: A list of dictionaries, every dictionary represents a RAID
            controller summary of node.
        """
        driver_info = utils.parse_driver_info(task.node)
        with ibmc_client.connect(**driver_info) as conn:
            controllers = conn.system.storage.list()
            summaries = [ctrl.summary() for ctrl in controllers]
            return summaries
