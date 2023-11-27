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
DRAC vendor-passthru interface
"""

from ironic_lib import metrics_utils
from oslo_log import log as logging

from ironic.common.i18n import _
from ironic.conductor import task_manager
from ironic.drivers import base
from ironic.drivers.modules.drac import bios as drac_bios
from ironic.drivers.modules.drac import common as drac_common
from ironic.drivers.modules.drac import job as drac_job
from ironic.drivers.modules.redfish import vendor as redfish_vendor

LOG = logging.getLogger(__name__)

METRICS = metrics_utils.get_metrics_logger(__name__)


class DracWSManVendorPassthru(base.VendorInterface):
    """Interface for DRAC specific methods."""

    # NOTE(TheJulia): Deprecating November 2023 in favor of Redfish
    # and due to a lack of active driver maintenance.
    supported = False

    def get_properties(self):
        """Return the properties of the interface."""
        return drac_common.COMMON_PROPERTIES

    @METRICS.timer('DracVendorPassthru.validate')
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

    @METRICS.timer('DracVendorPassthru.get_bios_config')
    @base.passthru(['GET'], async_call=False,
                   description=_("Returns a dictionary containing the BIOS "
                                 "settings from a node."))
    def get_bios_config(self, task, **kwargs):
        """Get the BIOS configuration.

        This method is used to retrieve the BIOS settings from a node.

        :param task: a TaskManager instance containing the node to act on.
        :param kwargs: not used.
        :raises: DracOperationError on an error from python-dracclient.
        :returns: a dictionary containing BIOS settings.
        """
        bios_attrs = {}
        for name, bios_attr in drac_bios.get_config(task.node).items():
            bios_attrs[name] = bios_attr.__dict__

        return bios_attrs

    @METRICS.timer('DracVendorPassthru.set_bios_config')
    @base.passthru(['POST'], async_call=False,
                   description=_("Change the BIOS configuration on a node. "
                                 "Required argument : a dictionary of "
                                 "{'AttributeName': 'NewValue'}. Returns "
                                 "a dictionary containing the "
                                 "'is_commit_required' key with a Boolean "
                                 "value indicating whether "
                                 "commit_bios_config() needs to be called "
                                 "to make the changes, and the "
                                 "'is_reboot_required' key with a value of "
                                 "'true' or 'false'.  This key is used to "
                                 "indicate to the commit_bios_config() call "
                                 "if a reboot should be performed."))
    @task_manager.require_exclusive_lock
    def set_bios_config(self, task, **kwargs):
        """Change BIOS settings.

        This method is used to change the BIOS settings on a node.

        :param task: a TaskManager instance containing the node to act on.
        :param kwargs: a dictionary of {'AttributeName': 'NewValue'}
        :raises: DracOperationError on an error from python-dracclient.
        :returns: A dictionary containing the ``is_commit_required`` key with a
                  Boolean value indicating whether commit_bios_config() needs
                  to be called to make the changes, and the
                  ``is_reboot_required`` key with a value of 'true' or 'false'.
                  This key is used to indicate to the commit_bios_config() call
                  if a reboot should be performed.
        """
        return drac_bios.set_config(task, **kwargs)

    @METRICS.timer('DracVendorPassthru.commit_bios_config')
    @base.passthru(['POST'], async_call=False,
                   description=_("Commit a BIOS configuration job submitted "
                                 "through set_bios_config(). Required "
                                 "argument: 'reboot' - indicates whether a "
                                 "reboot job should be automatically created "
                                 "with the config job. Returns a dictionary "
                                 "containing the 'job_id' key with the ID of "
                                 "the newly created config job, and the "
                                 "'reboot_required' key indicating whether "
                                 "the node needs to be rebooted to start the "
                                 "config job."))
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
        :returns: A dictionary containing the ``job_id`` key with the id of the
                  newly created config job, and the ``reboot_required`` key
                  indicating whether the node needs to be rebooted to start the
                  config job.
        """
        job_id = drac_bios.commit_config(task, reboot=reboot)
        return {'job_id': job_id, 'reboot_required': not reboot}

    @METRICS.timer('DracVendorPassthru.abandon_bios_config')
    @base.passthru(['DELETE'], async_call=False,
                   description=_("Abandon a BIOS configuration job previously "
                                 "submitted through set_bios_config()."))
    @task_manager.require_exclusive_lock
    def abandon_bios_config(self, task, **kwargs):
        """Abandon a BIOS configuration job.

        This method is used to abandon a BIOS configuration previously
        submitted through set_bios_config().

        :param task: a TaskManager instance containing the node to act on.
        :param kwargs: not used.
        :raises: DracOperationError on an error from python-dracclient.
        """
        drac_bios.abandon_config(task)

    @base.passthru(['GET'], async_call=False,
                   description=_('Returns a dictionary containing the key '
                                 '"unfinished_jobs"; its value is a list of '
                                 'dictionaries. Each dictionary represents '
                                 'an unfinished config Job object.'))
    def list_unfinished_jobs(self, task, **kwargs):
        """List unfinished config jobs of the node.

        :param task: a TaskManager instance containing the node to act on.
        :param kwargs: not used.
        :returns: a dictionary containing the ``unfinished_jobs`` key; this key
                  points to a list of dicts, with each dict representing a Job
                  object.
        :raises: DracOperationError on an error from python-dracclient.
        """
        jobs = drac_job.list_unfinished_jobs(task.node)
        # FIXME(mgould) Do this without calling private methods.
        return {'unfinished_jobs': [job._asdict() for job in jobs]}


class DracVendorPassthru(DracWSManVendorPassthru):
    """Class alias of class DracWSManVendorPassthru.

    This class provides ongoing support of the deprecated 'idrac' vendor
    passthru interface implementation entrypoint.

    All bug fixes and new features should be implemented in its base
    class, DracWSManVendorPassthru. That makes them available to both
    the deprecated 'idrac' and new 'idrac-wsman' entrypoints. Such
    changes should not be made to this class.
    """

    def __init__(self):
        super(DracVendorPassthru, self).__init__()
        LOG.warning("Vendor passthru interface 'idrac' is deprecated and may "
                    "be removed in a future release. Use 'idrac-wsman' "
                    "instead.")


class DracRedfishVendorPassthru(redfish_vendor.RedfishVendorPassthru):
    """iDRAC Redfish interface for vendor_passthru.

    Use the Redfish implementation for vendor passthru.
    """
