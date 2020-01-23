# Copyright 2018 FUJITSU LIMITED
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
iRMC BIOS configuration specific methods
"""
from ironic_lib import metrics_utils
from oslo_log import log as logging
from oslo_utils import importutils

from ironic.common import exception
from ironic.drivers import base
from ironic.drivers.modules.irmc import common as irmc_common
from ironic import objects


irmc = importutils.try_import('scciclient.irmc')

LOG = logging.getLogger(__name__)

METRICS = metrics_utils.get_metrics_logger(__name__)


class IRMCBIOS(base.BIOSInterface):

    supported = False

    def get_properties(self):
        """Return the properties of the interface."""
        return irmc_common.COMMON_PROPERTIES

    @METRICS.timer('IRMCBIOS.validate')
    def validate(self, task):
        """Validate the driver-specific Node info.

        This method validates whether the 'driver_info' property of the
        supplied node contains the required information for this driver to
        manage the BIOS settings of the node.

        :param task: a TaskManager instance containing the node to act on.
        :raises: InvalidParameterValue if required driver_info attribute
                 is missing or invalid on the node.
        :raises: MissingParameterValue if a required parameter is missing
         in the driver_info property.
        """
        irmc_common.parse_driver_info(task.node)

    @METRICS.timer('IRMCBIOS.apply_configuration')
    @base.clean_step(priority=0, abortable=False, argsinfo={
        'settings': {
            'description': "Dictionary containing the BIOS configuration.",
            'required': True
        }
    })
    @base.cache_bios_settings
    def apply_configuration(self, task, settings):
        """Applies BIOS configuration on the given node.

        This method takes the BIOS settings from the settings param and
        applies BIOS configuration on the given node.
        After the BIOS configuration is done, self.cache_bios_settings() may
        be called to sync the node's BIOS-related information with the BIOS
        configuration applied on the node.
        It will also validate the given settings before applying any
        settings and manage failures when setting an invalid BIOS config.
        In the case of needing password to update the BIOS config, it will be
        taken from the driver_info properties.

        :param task: a TaskManager instance.
        :param settings: Dictionary containing the BIOS configuration. It
            may be an empty dictionary as well.
        :raises: IRMCOperationError,if apply bios settings failed.
        """

        irmc_info = irmc_common.parse_driver_info(task.node)

        try:
            LOG.info('Apply BIOS configuration for node %(node_uuid)s: '
                     '%(settings)s', {'settings': settings,
                                      'node_uuid': task.node.uuid})
            irmc.elcm.set_bios_configuration(irmc_info, settings)
            # NOTE(trungnv): Fix failed cleaning during rebooting node
            # when combine OOB and IB steps in manual clean.
            self._resume_cleaning(task)
        except irmc.scci.SCCIError as e:
            LOG.error('Failed to apply BIOS configuration on node '
                      '%(node_uuid)s. Error: %(error)s',
                      {'node_uuid': task.node.uuid, 'error': e})
            raise exception.IRMCOperationError(
                operation='Apply BIOS configuration', error=e)

    @METRICS.timer('IRMCBIOS.factory_reset')
    @base.cache_bios_settings
    def factory_reset(self, task):
        """Reset BIOS configuration to factory default on the given node.

        :param task: a TaskManager instance.
        :raises: UnsupportedDriverExtension, if the node's driver doesn't
            support BIOS reset.
        """

        raise exception.UnsupportedDriverExtension(
            driver=task.node.driver, extension='factory_reset')

    @METRICS.timer('IRMCBIOS.cache_bios_settings')
    def cache_bios_settings(self, task):
        """Store or update BIOS settings on the given node.

        This method stores BIOS properties to the bios settings db

        :param task: a TaskManager instance.
        :raises: IRMCOperationError,if get bios settings failed.
        :returns: None if it is complete.
        """

        irmc_info = irmc_common.parse_driver_info(task.node)
        node_id = task.node.id
        try:
            settings = irmc.elcm.get_bios_settings(irmc_info)
        except irmc.scci.SCCIError as e:
            LOG.error('Failed to retrieve the current BIOS settings for node '
                      '%(node)s. Error: %(error)s', {'node': task.node.uuid,
                                                     'error': e})
            raise exception.IRMCOperationError(operation='Cache BIOS settings',
                                               error=e)
        create_list, update_list, delete_list, nochange_list = (
            objects.BIOSSettingList.sync_node_setting(task.context, node_id,
                                                      settings))
        if len(create_list) > 0:
            objects.BIOSSettingList.create(task.context, node_id, create_list)
        if len(update_list) > 0:
            objects.BIOSSettingList.save(task.context, node_id, update_list)
        if len(delete_list) > 0:
            delete_names = [setting['name'] for setting in delete_list]
            objects.BIOSSettingList.delete(task.context, node_id,
                                           delete_names)

    def _resume_cleaning(self, task):
        driver_internal_info = task.node.driver_internal_info
        driver_internal_info['cleaning_reboot'] = True
        task.node.driver_internal_info = driver_internal_info
        task.node.save()
