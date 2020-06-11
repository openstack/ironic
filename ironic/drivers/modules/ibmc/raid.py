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
iBMC RAID configuration specific methods
"""

from ironic_lib import metrics_utils
from oslo_log import log as logging
from oslo_utils import importutils

from ironic.common.i18n import _
from ironic.common import raid
from ironic import conf
from ironic.drivers import base
from ironic.drivers.modules.ibmc import utils

constants = importutils.try_import('ibmc_client.constants')
ibmc_client = importutils.try_import('ibmc_client')
ibmc_error = importutils.try_import('ibmc_client.exceptions')

CONF = conf.CONF
LOG = logging.getLogger(__name__)
METRICS = metrics_utils.get_metrics_logger(__name__)


class IbmcRAID(base.RAIDInterface):
    """Implementation of RAIDInterface for iBMC."""

    RAID_APPLY_CONFIGURATION_ARGSINFO = {
        "raid_config": {
            "description": "The RAID configuration to apply.",
            "required": True,
        },
        "create_root_volume": {
            "description": (
                "Setting this to 'False' indicates not to create root "
                "volume that is specified in 'raid_config'. Default "
                "value is 'True'."
            ),
            "required": False,
        },
        "create_nonroot_volumes": {
            "description": (
                "Setting this to 'False' indicates not to create "
                "non-root volumes (all except the root volume) in "
                "'raid_config'. Default value is 'True'."
            ),
            "required": False,
        },
        "delete_existing": {
            "description": (
                "Setting this to 'True' indicates to delete existing RAID "
                "configuration prior to creating the new configuration. "
                "Default value is 'True'."
            ),
            "required": False,
        }
    }

    def get_properties(self):
        """Return the properties of the interface.

        :returns: dictionary of <property name>:<property description> entries.
        """
        return utils.COMMON_PROPERTIES.copy()

    @utils.handle_ibmc_exception('delete iBMC RAID configuration')
    def _delete_raid_configuration(self, task):
        """Delete the RAID configuration through `python-ibmcclient` lib.

        :param task: a TaskManager instance containing the node to act on.
        """
        ibmc = utils.parse_driver_info(task.node)
        with ibmc_client.connect(**ibmc) as conn:
            # NOTE(qianbiao.ng): To reduce review workload, we should keep all
            # delete logic in python-ibmcclient. And delete raid configuration
            # logic should be synchronized. if async required, do it in
            # python-ibmcclient.
            conn.system.storage.delete_all_raid_configuration()

    @utils.handle_ibmc_exception('create iBMC RAID configuration')
    def _create_raid_configuration(self, task, logical_disks):
        """Create the RAID configuration through `python-ibmcclient` lib.

        :param task: a TaskManager instance containing the node to act on.
        :param logical_disks: a list of JSON dictionaries which represents
            the logical disks to be created. The JSON dictionary should match
            the (ironic.drivers.raid_config_schema.json) scheme.
        """
        ibmc = utils.parse_driver_info(task.node)
        with ibmc_client.connect(**ibmc) as conn:
            # NOTE(qianbiao.ng): To reduce review workload, we should keep all
            # apply logic in python-ibmcclient. And apply raid configuration
            # logic should be synchronized. if async required, do it in
            # python-ibmcclient.
            conn.system.storage.apply_raid_configuration(logical_disks)

    @base.deploy_step(priority=0,
                      argsinfo=RAID_APPLY_CONFIGURATION_ARGSINFO)
    def apply_configuration(self, task, raid_config, create_root_volume=True,
                            create_nonroot_volumes=False):
        return super(IbmcRAID, self).apply_configuration(
            task, raid_config, create_root_volume=create_root_volume,
            create_nonroot_volumes=create_nonroot_volumes)

    @METRICS.timer('IbmcRAID.create_configuration')
    @base.clean_step(priority=0, abortable=False, argsinfo={
        'create_root_volume': {
            'description': ('This specifies whether to create the root '
                            'volume. Defaults to `True`.'),
            'required': False
        },
        'create_nonroot_volumes': {
            'description': ('This specifies whether to create the non-root '
                            'volumes. Defaults to `True`.'),
            'required': False
        },
        "delete_existing": {
            "description": ("Setting this to 'True' indicates to delete "
                            "existing RAID configuration prior to creating "
                            "the new configuration. "
                            "Default value is 'False'."),
            "required": False,
        }
    })
    def create_configuration(self, task, create_root_volume=True,
                             create_nonroot_volumes=True,
                             delete_existing=False):
        """Create a RAID configuration.

        This method creates a RAID configuration on the given node.

        :param task: a TaskManager instance.
        :param create_root_volume: If True, a root volume is created
            during RAID configuration. Otherwise, no root volume is
            created. Default is True.
        :param create_nonroot_volumes: If True, non-root volumes are
            created. If False, no non-root volumes are created. Default
            is True.
        :param delete_existing: Setting this to True indicates to delete RAID
            configuration prior to creating the new configuration. Default is
            False.
        :raises: MissingParameterValue, if node.target_raid_config is missing
            or empty after skipping root volume and/or non-root volumes.
        :raises: IBMCError, on failure to execute step.
        """
        node = task.node
        raid_config = raid.filter_target_raid_config(
            node, create_root_volume=create_root_volume,
            create_nonroot_volumes=create_nonroot_volumes)
        LOG.info(_("Invoke RAID create_configuration step for node %s(uuid). "
                   "Current provision state is: %(status)s. "
                   "Target RAID configuration is: %(config)s."),
                 {'uuid': node.uuid, 'status': node.provision_state,
                  'target': raid_config})

        # cache current raid config to node's driver_internal_info
        node.driver_internal_info['raid_config'] = raid_config
        node.save()

        # delete exist volumes if necessary
        if delete_existing:
            self._delete_raid_configuration(task)

        # create raid configuration
        logical_disks = raid_config.get('logical_disks', [])
        self._create_raid_configuration(task, logical_disks)
        LOG.info(_("Succeed to create raid configuration on node %s."),
                 task.node.uuid)

    @METRICS.timer('IbmcRAID.delete_configuration')
    @base.clean_step(priority=0, abortable=False)
    @base.deploy_step(priority=0)
    def delete_configuration(self, task):
        """Delete the RAID configuration.

        :param task: a TaskManager instance containing the node to act on.
        :returns: states.CLEANWAIT if cleaning operation in progress
            asynchronously or states.DEPLOYWAIT if deploy operation in
            progress synchronously or None if it is completed.
        :raises: IBMCError, on failure to execute step.
        """
        node = task.node
        LOG.info("Invoke RAID delete_configuration step for node %s(uuid). "
                 "Current provision state is: %(status)s. ",
                 {'uuid': node.uuid, 'status': node.provision_state})
        self._delete_raid_configuration(task)
        LOG.info(_("Succeed to delete raid configuration on node %s."),
                 task.node.uuid)
