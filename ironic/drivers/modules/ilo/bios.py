# Copyright 2018 Hewlett-Packard Development Company, L.P.
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
iLO BIOS Interface
"""

from ironic_lib import metrics_utils
from oslo_log import log as logging
from oslo_utils import importutils

from ironic.common import exception
from ironic.common.i18n import _
from ironic.drivers import base
from ironic.drivers.modules import deploy_utils
from ironic.drivers.modules.ilo import common as ilo_common
from ironic import objects

LOG = logging.getLogger(__name__)
METRICS = metrics_utils.get_metrics_logger(__name__)

ilo_error = importutils.try_import('proliantutils.exception')


class IloBIOS(base.BIOSInterface):

    _APPLY_CONFIGURATION_ARGSINFO = {
        'settings': {
            'description': 'Dictionary with current BIOS configuration.',
            'required': True
        }
    }

    def get_properties(self):
        return ilo_common.REQUIRED_PROPERTIES

    @METRICS.timer('IloBIOS.validate')
    def validate(self, task):
        """Check that 'driver_info' contains required ILO credentials.

        Validates whether the 'driver_info' property of the supplied
        task's node contains the required credentials information.

        :param task: a task from TaskManager.
        :raises: InvalidParameterValue if required iLO parameters
                 are not valid.
        :raises: MissingParameterValue if a required parameter is missing.
        """
        ilo_common.parse_driver_info(task.node)

    def _execute_pre_boot_bios_step(self, task, step, data=None):
        """Perform operations required prior to the reboot.

        Depending on the step, it executes the operations required
        and moves the node to CLEANWAIT or DEPLOYWAIT state prior to reboot
        based on the operation being performed.
        :param task: a task from TaskManager.
        :param step: name of the clean step to be performed
        :param data: if the clean step is apply_configuration it holds
                     the settings data.
        :raises: NodeCleaningFailure, on failure to execute of clean step.
        :raises: InstanceDeployFailure, on failure to execute of deploy step.
        """
        node = task.node

        if step not in ('apply_configuration', 'factory_reset'):
            errmsg = (_('Could not find the step %(step)s for the '
                        'node %(node)s.')
                      % {'step': step, 'node': node.uuid})
            if node.clean_step:
                raise exception.NodeCleaningFailure(errmsg)
            raise exception.InstanceDeployFailure(reason=errmsg)

        try:
            ilo_object = ilo_common.get_ilo_object(node)
            ilo_object.set_bios_settings(data) if step == (
                'apply_configuration') else ilo_object.reset_bios_to_default()
        except (exception.MissingParameterValue,
                exception.InvalidParameterValue,
                ilo_error.IloError,
                ilo_error.IloCommandNotSupportedError) as ir_exception:
            errmsg = (_('Step %(step)s failed '
                        'on the node %(node)s with error: %(err)s')
                      % {'step': step, 'node': node.uuid, 'err': ir_exception})
            if node.clean_step:
                raise exception.NodeCleaningFailure(errmsg)
            raise exception.InstanceDeployFailure(reason=errmsg)

        return_state = deploy_utils.reboot_to_finish_step(task)

        deploy_utils.set_async_step_flags(node, reboot=True,
                                          skip_current_step=False)
        if step == 'apply_configuration':
            node.set_driver_internal_info('apply_bios', True)
        else:
            node.set_driver_internal_info('reset_bios', True)

        node.save()
        return return_state

    def _execute_post_boot_bios_step(self, task, step):
        """Perform operations required after the reboot.

        Caches BIOS settings in the database and clear the flags assocated
        with the clean step post reboot.
        :param task: a task from TaskManager.
        :param step: name of the clean step to be performed
        :raises: NodeCleaningFailure, on failure to execute of clean step.
        :raises: InstanceDeployFailure, on failure to execute of deploy step.
        """
        node = task.node

        node.del_driver_internal_info('apply_bios')
        node.del_driver_internal_info('reset_bios')
        node.save()

        if step not in ('apply_configuration', 'factory_reset'):
            errmsg = (_('Could not find the step %(step)s for the '
                        'node %(node)s.')
                      % {'step': step, 'node': node.uuid})
            if node.clean_step:
                raise exception.NodeCleaningFailure(errmsg)
            raise exception.InstanceDeployFailure(reason=errmsg)

        try:
            ilo_object = ilo_common.get_ilo_object(node)
            status = ilo_object.get_bios_settings_result()
        except (exception.MissingParameterValue,
                exception.InvalidParameterValue,
                ilo_error.IloError,
                ilo_error.IloCommandNotSupportedError) as ir_exception:
            errmsg = (_('Step %(step)s failed '
                        'on the node %(node)s with error: %(err)s')
                      % {'step': step, 'node': node.uuid, 'err': ir_exception})
            if node.clean_step:
                raise exception.NodeCleaningFailure(errmsg)
            raise exception.InstanceDeployFailure(reason=errmsg)

        if status.get('status') == 'failed':
            errmsg = (_('Step %(step)s failed '
                        'on the node %(node)s with error: %(err)s')
                      % {'step': step, 'node': node.uuid,
                         'err': status.get('results')})
            if node.clean_step:
                raise exception.NodeCleaningFailure(errmsg)
            raise exception.InstanceDeployFailure(reason=errmsg)

    @METRICS.timer('IloBIOS.apply_configuration')
    @base.deploy_step(priority=0, argsinfo=_APPLY_CONFIGURATION_ARGSINFO)
    @base.clean_step(priority=0, abortable=False,
                     argsinfo=_APPLY_CONFIGURATION_ARGSINFO)
    @base.cache_bios_settings
    def apply_configuration(self, task, settings):
        """Applies the provided configuration on the node.

        :param task: a TaskManager instance.
        :param settings: Settings intended to be applied on the node.
        :raises: NodeCleaningFailure, on failure to execute of clean step.
        :raises: InstanceDeployFailure, on failure to execute of deploy step.

        """
        node = task.node
        data = {}
        for setting in settings:
            data.update({setting['name']: setting['value']})
        if not node.driver_internal_info.get('apply_bios'):
            return self._execute_pre_boot_bios_step(
                task, 'apply_configuration', data)
        else:
            return self._execute_post_boot_bios_step(
                task, 'apply_configuration')

    @METRICS.timer('IloBIOS.factory_reset')
    @base.deploy_step(priority=0)
    @base.clean_step(priority=0, abortable=False)
    @base.cache_bios_settings
    def factory_reset(self, task):
        """Reset the BIOS settings to factory configuration.

        :param task: a TaskManager instance.
        :raises: NodeCleaningFailure, on failure to execute of clean step.
        :raises: InstanceDeployFailure, on failure to execute of deploy step.

        """
        node = task.node

        if not node.driver_internal_info.get('reset_bios'):
            return self._execute_pre_boot_bios_step(task, 'factory_reset')
        else:
            return self._execute_post_boot_bios_step(task, 'factory_reset')

    @METRICS.timer('IloBIOS.cache_bios_settings')
    def cache_bios_settings(self, task):
        """Store the BIOS settings in the database.

        :param task: a TaskManager instance.
        :raises: NodeCleaningFailure, on failure to execute of clean step.
        :raises: InstanceDeployFailure, on failure to execute of deploy step.

        """
        node = task.node
        nodeid = node.id

        try:
            ilo_object = ilo_common.get_ilo_object(node)
            bios_settings = ilo_object.get_current_bios_settings()

        except (exception.MissingParameterValue,
                exception.InvalidParameterValue,
                ilo_error.IloError,
                ilo_error.IloCommandNotSupportedError) as ir_exception:
            errmsg = (_("Caching BIOS settings failed "
                        "on node %(node)s with error: %(err)s")
                      % {'node': node.uuid, 'err': ir_exception})
            if node.clean_step:
                raise exception.NodeCleaningFailure(errmsg)
            raise exception.InstanceDeployFailure(reason=errmsg)

        fmt_bios_settings = []

        for setting in bios_settings:
            fmt_bios_settings.append({"name": setting,
                                      "value": bios_settings[setting]})

        create_list, update_list, delete_list, nochange_list = (
            objects.BIOSSettingList.sync_node_setting(task.context,
                                                      nodeid,
                                                      fmt_bios_settings))
        if len(create_list) > 0:
            objects.BIOSSettingList.create(task.context, nodeid, create_list)
        if len(update_list) > 0:
            objects.BIOSSettingList.save(task.context, nodeid, update_list)
        if len(delete_list) > 0:
            delete_name_list = [delete_name.get(
                "name") for delete_name in delete_list]
            objects.BIOSSettingList.delete(
                task.context, nodeid, delete_name_list)
