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
DRAC VendorPassthruBios Driver
"""

from ironic.drivers import base
from ironic.drivers.modules.drac import bios
from ironic.drivers.modules.drac import common as drac_common


class DracVendorPassthru(base.VendorInterface):
    """Interface for DRAC specific BIOS configuration methods."""

    def get_properties(self):
        """Returns the driver_info properties.

        This method returns the driver_info properties for this driver.

        :returns: a dictionary of propery names and their descriptions.
        """
        return drac_common.COMMON_PROPERTIES

    def validate(self, task, **kwargs):
        """Validates the driver_info of a node.

        This method validates the driver_info associated with the node that is
        associated with the task.

        :param task: the ironic task used to identify the node.
        :param kwargs: not used.
        :raises: InvalidParameterValue if mandatory information is missing on
                 the node or any driver_info is invalid.
        :returns: a dict containing information from driver_info
                  and default values.
        """
        return drac_common.parse_driver_info(task.node)

    @base.passthru(['GET'], async=False)
    def get_bios_config(self, task, **kwargs):
        """Get BIOS settings.

        This method is used to retrieve the BIOS settings from a node.

        :param task: the ironic task used to identify the node.
        :param kwargs: not used.
        :raises: DracClientError on an error from pywsman.
        :raises: DracOperationFailed when a BIOS setting cannot be parsed.
        :returns: a dictionary containing BIOS settings.
        """
        return bios.get_config(task.node)

    @base.passthru(['POST'], async=False)
    def set_bios_config(self, task, **kwargs):
        """Change BIOS settings.

        This method is used to change the BIOS settings on a node.

        :param task: the ironic task used to identify the node.
        :param kwargs: a dictionary of {'AttributeName': 'NewValue'}
        :raises: DracOperationFailed if any of the attributes cannot be set for
                 any reason.
        :raises: DracClientError on an error from the pywsman library.
        :returns: A dictionary containing the commit_needed key with a boolean
                  value indicating whether commit_config() needs to be called
                  to make the changes.
        """
        return {'commit_needed': bios.set_config(task, **kwargs)}

    @base.passthru(['POST'], async=False)
    def commit_bios_config(self, task, reboot=False, **kwargs):
        """Commit a BIOS configuration job.

        This method is used to commit a BIOS configuration job.
        submitted through set_bios_config().

        :param task: the ironic task for running the config job.
        :param reboot: indicates whether a reboot job should be automatically
                       created with the config job.
        :param kwargs: additional arguments sent via vendor passthru.
        :raises: DracClientError on an error from pywsman library.
        :raises: DracPendingConfigJobExists if the job is already created.
        :raises: DracOperationFailed if the client received response with an
                 error message.
        :raises: DracUnexpectedReturnValue if the client received a response
                 with unexpected return value
        :returns: A dictionary containing the committing key with no return
                  value, and the reboot_needed key with a value of True.
        """
        bios.commit_config(task, reboot=reboot)
        return {'committing': None, 'reboot_needed': not reboot}

    @base.passthru(['DELETE'], async=False)
    def abandon_bios_config(self, task, **kwargs):
        """Abandon a BIOS configuration job.

        This method is used to abandon a BIOS configuration job previously
        submitted through set_bios_config().

        :param task: the ironic task for abandoning the changes.
        :param kwargs: not used.
        :raises: DracClientError on an error from pywsman library.
        :raises: DracOperationFailed on error reported back by DRAC.
        :raises: DracUnexpectedReturnValue if the drac did not report success.
        :returns: A dictionary containing the abandoned key with no return
                  value.
        """
        bios.abandon_config(task)
        return {'abandoned': None}
