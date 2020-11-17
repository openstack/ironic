# Copyright 2018 Hewlett Packard Enterprise Development LP
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
iLO5 RAID specific methods
"""

from ironic_lib import metrics_utils
from oslo_log import log as logging
from oslo_utils import importutils

from ironic.common import exception
from ironic.common.i18n import _
from ironic.common import raid
from ironic.common import states
from ironic.conductor import utils as manager_utils
from ironic import conf
from ironic.drivers import base
from ironic.drivers.modules import deploy_utils
from ironic.drivers.modules.ilo import common as ilo_common


LOG = logging.getLogger(__name__)
CONF = conf.CONF
METRICS = metrics_utils.get_metrics_logger(__name__)

ilo_error = importutils.try_import('proliantutils.exception')


class Ilo5RAID(base.RAIDInterface):
    """Implementation of OOB RAIDInterface for iLO5."""

    _RAID_APPLY_CONFIGURATION_ARGSINFO = {
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
        }
    }

    def get_properties(self):
        """Return the properties of the interface."""
        return ilo_common.REQUIRED_PROPERTIES

    def _set_step_failed(self, task, msg, exc):
        log_msg = ("RAID configuration job failed for node %(node)s. "
                   "Message: '%(message)s'." %
                   {'node': task.node.uuid, 'message': msg})
        if task.node.provision_state == states.DEPLOYING:
            manager_utils.deploying_error_handler(task, log_msg, errmsg=msg)
        else:
            manager_utils.cleaning_error_handler(task, log_msg, errmsg=msg)

    def _set_driver_internal_true_value(self, task, *keys):
        driver_internal_info = task.node.driver_internal_info
        for key in keys:
            driver_internal_info[key] = True
        task.node.driver_internal_info = driver_internal_info
        task.node.save()

    def _set_driver_internal_false_value(self, task, *keys):
        driver_internal_info = task.node.driver_internal_info
        for key in keys:
            driver_internal_info[key] = False
        task.node.driver_internal_info = driver_internal_info
        task.node.save()

    def _pop_driver_internal_values(self, task, *keys):
        driver_internal_info = task.node.driver_internal_info
        for key in keys:
            driver_internal_info.pop(key, None)
        task.node.driver_internal_info = driver_internal_info
        task.node.save()

    def _prepare_for_read_raid(self, task, raid_step):
        deploy_opts = deploy_utils.build_agent_options(task.node)
        task.driver.boot.prepare_ramdisk(task, deploy_opts)
        manager_utils.node_power_action(task, states.REBOOT)
        if raid_step == 'create_raid':
            self._set_driver_internal_true_value(
                task, 'ilo_raid_create_in_progress')
        else:
            self._set_driver_internal_true_value(
                task, 'ilo_raid_delete_in_progress')
        deploy_utils.set_async_step_flags(task.node, reboot=True,
                                          skip_current_step=False)

    @base.deploy_step(priority=0,
                      argsinfo=_RAID_APPLY_CONFIGURATION_ARGSINFO)
    def apply_configuration(self, task, raid_config, create_root_volume=True,
                            create_nonroot_volumes=False):
        return super(Ilo5RAID, self).apply_configuration(
            task, raid_config, create_root_volume=create_root_volume,
            create_nonroot_volumes=create_nonroot_volumes)

    @METRICS.timer('Ilo5RAID.create_configuration')
    @base.clean_step(priority=0, abortable=False, argsinfo={
        'create_root_volume': {
            'description': (
                'This specifies whether to create the root volume. '
                'Defaults to `True`.'
            ),
            'required': False
        },
        'create_nonroot_volumes': {
            'description': (
                'This specifies whether to create the non-root volumes. '
                'Defaults to `True`.'
            ),
            'required': False
        }
    })
    def create_configuration(self, task, create_root_volume=True,
                             create_nonroot_volumes=True):
        """Create a RAID configuration on a bare metal using agent ramdisk.

        This method creates a RAID configuration on the given node.

        :param task: a TaskManager instance.
        :param create_root_volume: If True, a root volume is created
            during RAID configuration. Otherwise, no root volume is
            created. Default is True.
        :param create_nonroot_volumes: If True, non-root volumes are
            created. If False, no non-root volumes are created. Default
            is True.
        :raises: MissingParameterValue, if node.target_raid_config is missing
            or was found to be empty after skipping root volume and/or non-root
            volumes.
        :raises: NodeCleaningFailure, on failure to execute clean step.
        :raises: InstanceDeployFailure, on failure to execute deploy step.
        """
        node = task.node
        target_raid_config = raid.filter_target_raid_config(
            node, create_root_volume=create_root_volume,
            create_nonroot_volumes=create_nonroot_volumes)
        driver_internal_info = node.driver_internal_info
        driver_internal_info['target_raid_config'] = target_raid_config
        node.driver_internal_info = driver_internal_info
        node.save()
        LOG.debug("Calling OOB RAID create_configuration for node %(node)s "
                  "with the following target RAID configuration: %(target)s",
                  {'node': node.uuid, 'target': target_raid_config})
        ilo_object = ilo_common.get_ilo_object(node)

        try:
            # Raid configuration in progress, checking status
            if not driver_internal_info.get('ilo_raid_create_in_progress'):
                ilo_object.create_raid_configuration(target_raid_config)
                self._prepare_for_read_raid(task, 'create_raid')
                return deploy_utils.get_async_step_return_state(node)
            else:
                # Raid configuration is done, updating raid_config
                raid_conf = (
                    ilo_object.read_raid_configuration(
                        raid_config=target_raid_config))
                fields = ['ilo_raid_create_in_progress']
                if node.clean_step:
                    fields.append('skip_current_clean_step')
                else:
                    fields.append('skip_current_deploy_step')
                self._pop_driver_internal_values(task, *fields)
                if len(raid_conf['logical_disks']):
                    raid.update_raid_info(node, raid_conf)
                    LOG.debug("Node %(uuid)s raid create clean step is done.",
                              {'uuid': node.uuid})
                else:
                    # Raid configuration failed
                    msg = (_("Step create_configuration failed "
                             "on node %(node)s with error: "
                             "Unable to create raid")
                           % {'node': node.uuid})
                    if node.clean_step:
                        raise exception.NodeCleaningFailure(msg)
                    else:
                        raise exception.InstanceDeployFailure(reason=msg)
        except ilo_error.IloError as ilo_exception:
            operation = (_("Failed to create raid configuration on node %s")
                         % node.uuid)
            fields = ['ilo_raid_create_in_progress']
            if node.clean_step:
                fields.append('skip_current_clean_step')
            else:
                fields.append('skip_current_deploy_step')
            self._pop_driver_internal_values(task, *fields)
            self._set_step_failed(task, operation, ilo_exception)

    @METRICS.timer('Ilo5RAID.delete_configuration')
    @base.clean_step(priority=0, abortable=False)
    @base.deploy_step(priority=0)
    def delete_configuration(self, task):
        """Delete the RAID configuration.

        :param task: a TaskManager instance  containing the node to act on.
        :raises: NodeCleaningFailure, on failure to execute clean step.
        :raises: InstanceDeployFailure, on failure to execute deploy step.
        """
        node = task.node
        LOG.debug("OOB RAID delete_configuration invoked for node %s.",
                  node.uuid)
        driver_internal_info = node.driver_internal_info
        ilo_object = ilo_common.get_ilo_object(node)

        try:
            # Raid configuration in progress, checking status
            if not driver_internal_info.get('ilo_raid_delete_in_progress'):
                ilo_object.delete_raid_configuration()
                self._prepare_for_read_raid(task, 'delete_raid')
                return deploy_utils.get_async_step_return_state(node)
            else:
                # Raid configuration is done, updating raid_config
                raid_conf = ilo_object.read_raid_configuration()
                fields = ['ilo_raid_delete_in_progress']
                if node.clean_step:
                    fields.append('skip_current_clean_step')
                else:
                    fields.append('skip_current_deploy_step')
                self._pop_driver_internal_values(task, *fields)
                if not len(raid_conf['logical_disks']):
                    node.raid_config = {}
                    LOG.debug("Node %(uuid)s raid delete clean step is done.",
                              {'uuid': node.uuid})
                else:
                    # Raid configuration failed
                    err_msg = (_("Step delete_configuration failed "
                                 "on node %(node)s with error: "
                                 "Unable to delete these logical disks: "
                                 "%(disks)s")
                               % {'node': node.uuid,
                                  'disks': raid_conf['logical_disks']})
                    if node.clean_step:
                        raise exception.NodeCleaningFailure(err_msg)
                    else:
                        raise exception.InstanceDeployFailure(reason=err_msg)
        except ilo_error.IloLogicalDriveNotFoundError:
            LOG.info("No logical drive found to delete on node %(node)s",
                     {'node': node.uuid})
        except ilo_error.IloError as ilo_exception:
            operation = (_("Failed to delete raid configuration on node %s")
                         % node.uuid)
            self._pop_driver_internal_values(task,
                                             'ilo_raid_delete_in_progress',
                                             'skip_current_clean_step')
            fields = ['ilo_raid_delete_in_progress']
            if node.clean_step:
                fields.append('skip_current_clean_step')
            else:
                fields.append('skip_current_deploy_step')
            self._pop_driver_internal_values(task, *fields)
            self._set_step_failed(task, operation, ilo_exception)
