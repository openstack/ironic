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

from ironic.conductor import task_manager
from ironic.drivers import base
from ironic.drivers.modules.drac import bios
from ironic.drivers.modules.drac import common as drac_common


class DracVendorPassthru(base.VendorInterface):
    """Interface for DRAC specific BIOS configuration methods."""

    def get_properties(self):
        """Return the properties of the interface."""
        return drac_common.COMMON_PROPERTIES

    def validate(self, task, **kwargs):
        """Validate the driver-specific info supplied.

        This method validates whether the 'driver_info' property of the
        supplied node contains the required information for this driver to
        manage the power state of the node.

        :param task: a TaskManager instance containing the node to act on.
        :param kwargs: not used.
        :raises: InvalidParameterValue if required driver_info attribute
                 is missing or invalid on the node.
        """
        return drac_common.parse_driver_info(task.node)

    @base.passthru(['GET'], async=False)
    def get_bios_config(self, task, **kwargs):
        """Get the BIOS configuration.

        This method is used to retrieve the BIOS settings from a node.

        :param task: a TaskManager instance containing the node to act on.
        :param kwargs: not used.
        :raises: DracOperationError on an error from python-dracclient.
        :returns: a dictionary containing BIOS settings.
        """
        bios_attrs = {}
        for name, bios_attr in bios.get_config(task.node).items():
            # NOTE(ifarkas): call from python-dracclient returns list of
            #                namedtuples, converting it to dict here.
            bios_attrs[name] = bios_attr.__dict__

        return bios_attrs

    @base.passthru(['POST'], async=False)
    @task_manager.require_exclusive_lock
    def set_bios_config(self, task, **kwargs):
        """Change BIOS settings.

        This method is used to change the BIOS settings on a node.

        :param task: a TaskManager instance containing the node to act on.
        :param kwargs: a dictionary of {'AttributeName': 'NewValue'}
        :raises: DracOperationError on an error from python-dracclient.
        :returns: A dictionary containing the commit_required key with a
                  Boolean value indicating whether commit_bios_config() needs
                  to be called to make the changes.
        """
        return bios.set_config(task, **kwargs)

    @base.passthru(['POST'], async=False)
    @task_manager.require_exclusive_lock
    def commit_bios_config(self, task, reboot=False, **kwargs):
        """Commit a BIOS configuration job.

        This method is used to commit a BIOS configuration job.
        submitted through set_bios_config().

        :param task: a TaskManager instance containing the node to act on.
        :param reboot: indicates whether a reboot job should be automatically
                       created with the config job.
        :param kwargs: not used.
        :raises: DracOperationError on an error from python-dracclient.
        :returns: A dictionary containing the job_id key with the id of the
                  newly created config job, and the reboot_required key
                  indicating whether to node needs to be rebooted to start the
                  config job.
        """
        job_id = bios.commit_config(task, reboot=reboot)
        return {'job_id': job_id, 'reboot_required': not reboot}

    @base.passthru(['DELETE'], async=False)
    @task_manager.require_exclusive_lock
    def abandon_bios_config(self, task, **kwargs):
        """Abandon a BIOS configuration job.

        This method is used to abandon a BIOS configuration previously
        submitted through set_bios_config().

        :param task: a TaskManager instance containing the node to act on.
        :param kwargs: not used.
        :raises: DracOperationError on an error from python-dracclient.
        """
        bios.abandon_config(task)
