# Copyright 2018 DMTF. All rights reserved.
#
#    Licensed under the Apache License, Version 2.0 (the "License"); you may
#    not use this file except in compliance with the License. You may obtain
#    a copy of the License at
#
#         http://www.apache.org/licenses/LICENSE-2.0
#
#    Unless required by applicable law or agreed to in writing, software
#    distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
#    WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
#    License for the specific language governing permissions and limitations
#    under the License.

from ironic_lib import metrics_utils
from oslo_log import log
from oslo_utils import importutils

from ironic.common import exception
from ironic.common.i18n import _
from ironic.common import states
from ironic.conductor import task_manager
from ironic.conductor import utils as manager_utils
from ironic.drivers import base
from ironic.drivers.modules import deploy_utils
from ironic.drivers.modules.redfish import utils as redfish_utils
from ironic import objects

LOG = log.getLogger(__name__)

METRICS = metrics_utils.get_metrics_logger(__name__)

sushy = importutils.try_import('sushy')

registry_fields = ('attribute_type', 'allowable_values', 'lower_bound',
                   'max_length', 'min_length', 'read_only',
                   'reset_required', 'unique', 'upper_bound')


class RedfishBIOS(base.BIOSInterface):

    _APPLY_CONFIGURATION_ARGSINFO = {
        'settings': {
            'description': (
                'A list of BIOS settings to be applied'
            ),
            'required': True
        }
    }

    def __init__(self):
        super(RedfishBIOS, self).__init__()
        if sushy is None:
            raise exception.DriverLoadError(
                driver='redfish',
                reason=_("Unable to import the sushy library"))

    def _parse_allowable_values(self, allowable_values):
        """Convert the BIOS registry allowable_value list to expected strings

        :param allowable_values: list of dicts of valid values for enumeration
        :returns: list containing only allowable value names
        """

        # Get name from ValueName if it exists, otherwise use DisplayValueName
        new_list = []
        for dic in allowable_values:
            for key in dic:
                if key == 'ValueName' or key == 'DisplayValueName':
                    new_list.append(dic[key])
                    break

        return new_list

    def cache_bios_settings(self, task):
        """Store or update the current BIOS settings for the node.

        Get the current BIOS settings and store them in the bios_settings
        database table.

        :param task: a TaskManager instance containing the node to act on.
        :raises: RedfishConnectionError when it fails to connect to Redfish
        :raises: RedfishError on an error from the Sushy library
        :raises: UnsupportedDriverExtension if the system does not support BIOS
            settings
        """

        node_id = task.node.id
        system = redfish_utils.get_system(task.node)
        try:
            attributes = system.bios.attributes
        except sushy.exceptions.MissingAttributeError:
            error_msg = _('Cannot fetch BIOS attributes for node %s, '
                          'BIOS settings are not supported.') % task.node.uuid
            LOG.error(error_msg)
            raise exception.UnsupportedDriverExtension(error_msg)

        settings = []
        # Convert Redfish BIOS attributes to Ironic BIOS settings
        if attributes:
            settings = [{'name': k, 'value': v}
                        for k, v in attributes.items()]

        # Get the BIOS Registry
        registry_attributes = []
        try:
            bios_registry = system.bios.get_attribute_registry()

            if bios_registry:
                registry_attributes = bios_registry.registry_entries.attributes

        except Exception as e:
            LOG.info('Cannot get BIOS Registry attributes for node %(node)s, '
                     'Error %(exc)s.', {'node': task.node.uuid, 'exc': e})

        # TODO(bfournier): use a common list for registry field names
        # e.g. registry_fields = objects.BIOSSetting.registry_fields

        # The BIOS registry will contain more entries than the BIOS settings
        # Find the registry entry matching the setting name and get the fields
        if registry_attributes:
            for setting in settings:
                reg = next((r for r in registry_attributes
                            if r.name == setting['name']), None)
                fields = [attr for attr in dir(reg)
                          if not attr.startswith("_")]
                settable_keys = [f for f in fields if f in registry_fields]
                # Set registry fields to current values
                for k in settable_keys:
                    setting[k] = getattr(reg, k, None)
                    if k == "allowable_values" and isinstance(setting[k],
                                                              list):
                        setting[k] = self._parse_allowable_values(setting[k])

        LOG.debug('Cache BIOS settings for node %(node_uuid)s',
                  {'node_uuid': task.node.uuid})

        create_list, update_list, delete_list, nochange_list = (
            objects.BIOSSettingList.sync_node_setting(
                task.context, node_id, settings))

        if create_list:
            objects.BIOSSettingList.create(
                task.context, node_id, create_list)
        if update_list:
            objects.BIOSSettingList.save(
                task.context, node_id, update_list)
        if delete_list:
            delete_names = [d['name'] for d in delete_list]
            objects.BIOSSettingList.delete(
                task.context, node_id, delete_names)

    @base.clean_step(priority=0)
    @base.deploy_step(priority=0)
    @base.cache_bios_settings
    def factory_reset(self, task):
        """Reset the BIOS settings of the node to the factory default.

        :param task: a TaskManager instance containing the node to act on.
        :raises: RedfishConnectionError when it fails to connect to Redfish
        :raises: RedfishError on an error from the Sushy library
        """
        system = redfish_utils.get_system(task.node)
        try:
            bios = system.bios
        except sushy.exceptions.MissingAttributeError:
            error_msg = (_('Redfish BIOS factory reset failed for node '
                           '%s, because BIOS settings are not supported.') %
                         task.node.uuid)
            LOG.error(error_msg)
            raise exception.RedfishError(error=error_msg)

        node = task.node
        info = node.driver_internal_info
        reboot_requested = info.get('post_factory_reset_reboot_requested')
        if not reboot_requested:
            LOG.debug('Factory reset BIOS configuration for node %(node)s',
                      {'node': node.uuid})
            try:
                bios.reset_bios()
            except sushy.exceptions.SushyError as e:
                error_msg = (_('Redfish BIOS factory reset failed for node '
                               '%(node)s. Error: %(error)s') %
                             {'node': node.uuid, 'error': e})
                LOG.error(error_msg)
                raise exception.RedfishError(error=error_msg)

            self.post_reset(task)
            self._set_reboot(task)
            return deploy_utils.get_async_step_return_state(task.node)
        else:
            current_attrs = bios.attributes
            LOG.debug('Post factory reset, BIOS configuration for node '
                      '%(node_uuid)s: %(attrs)r',
                      {'node_uuid': node.uuid, 'attrs': current_attrs})
            self._clear_reboot_requested(task)

    @base.clean_step(priority=0, argsinfo=_APPLY_CONFIGURATION_ARGSINFO)
    @base.deploy_step(priority=0, argsinfo=_APPLY_CONFIGURATION_ARGSINFO)
    @base.cache_bios_settings
    def apply_configuration(self, task, settings):
        """Apply the BIOS settings to the node.

        :param task: a TaskManager instance containing the node to act on.
        :param settings: a list of BIOS settings to be updated.
        :raises: RedfishConnectionError when it fails to connect to Redfish
        :raises: RedfishError on an error from the Sushy library
        """

        system = redfish_utils.get_system(task.node)
        try:
            bios = system.bios
        except sushy.exceptions.MissingAttributeError:
            error_msg = (_('Redfish BIOS factory reset failed for node '
                           '%s, because BIOS settings are not supported.') %
                         task.node.uuid)
            LOG.error(error_msg)
            raise exception.RedfishError(error=error_msg)

        # Convert Ironic BIOS settings to Redfish BIOS attributes
        attributes = {s['name']: s['value'] for s in settings}

        info = task.node.driver_internal_info
        reboot_requested = info.get('post_config_reboot_requested')

        if not reboot_requested:
            # Step 1: Apply settings and issue a reboot
            LOG.debug('Apply BIOS configuration for node %(node_uuid)s: '
                      '%(settings)r', {'node_uuid': task.node.uuid,
                                       'settings': settings})

            if bios.supported_apply_times and (
                    sushy.APPLY_TIME_ON_RESET in bios.supported_apply_times):
                apply_time = sushy.APPLY_TIME_ON_RESET
            else:
                apply_time = None

            try:
                bios.set_attributes(attributes, apply_time=apply_time)
            except sushy.exceptions.SushyError as e:
                error_msg = (_('Redfish BIOS apply configuration failed for '
                               'node %(node)s. Error: %(error)s') %
                             {'node': task.node.uuid, 'error': e})
                LOG.error(error_msg)
                raise exception.RedfishError(error=error_msg)

            self.post_configuration(task, settings)
            self._set_reboot_requested(task, attributes)
            return deploy_utils.get_async_step_return_state(task.node)
        else:
            # Step 2: Verify requested BIOS settings applied
            requested_attrs = info.get('requested_bios_attrs')
            current_attrs = bios.attributes
            LOG.debug('Verify BIOS configuration for node %(node_uuid)s: '
                      '%(attrs)r', {'node_uuid': task.node.uuid,
                                    'attrs': requested_attrs})
            self._clear_reboot_requested(task)
            self._check_bios_attrs(task, current_attrs, requested_attrs)

    def post_reset(self, task):
        """Perform post reset action to apply the BIOS factory reset.

        Extension point to allow vendor implementations to extend this class
        and override this method to perform a custom action to apply the BIOS
        factory reset to the Redfish service. The default implementation
        performs a reboot.

        :param task: a TaskManager instance containing the node to act on.
        """
        deploy_opts = deploy_utils.build_agent_options(task.node)
        task.driver.boot.prepare_ramdisk(task, deploy_opts)
        self._reboot(task)

    def post_configuration(self, task, settings):
        """Perform post configuration action to store the BIOS settings.

        Extension point to allow vendor implementations to extend this class
        and override this method to perform a custom action to write the BIOS
        settings to the Redfish service. The default implementation performs
        a reboot.

        :param task: a TaskManager instance containing the node to act on.
        :param settings: a list of BIOS settings to be updated.
        """
        deploy_opts = deploy_utils.build_agent_options(task.node)
        task.driver.boot.prepare_ramdisk(task, deploy_opts)
        self._reboot(task)

    def get_properties(self):
        """Return the properties of the interface.

        :returns: dictionary of <property name>:<property description> entries.
        """
        return redfish_utils.COMMON_PROPERTIES.copy()

    def validate(self, task):
        """Validates the driver information needed by the redfish driver.

        :param task: a TaskManager instance containing the node to act on.
        :raises: InvalidParameterValue on malformed parameter(s)
        :raises: MissingParameterValue on missing parameter(s)
        """
        redfish_utils.parse_driver_info(task.node)

    def _check_bios_attrs(self, task, current_attrs, requested_attrs):
        """Checks that the requested BIOS settings were applied to the service.

        :param task: a TaskManager instance containing the node to act on.
        :param current_attrs: the current BIOS attributes from the system.
        :param requested_attrs: the requested BIOS attributes to update.
        """

        attrs_not_updated = {}
        for attr in requested_attrs:
            if requested_attrs[attr] != current_attrs.get(attr):
                attrs_not_updated[attr] = requested_attrs[attr]

        if attrs_not_updated:
            LOG.debug('BIOS settings %(attrs)s for node %(node_uuid)s '
                      'not updated.', {'attrs': attrs_not_updated,
                                       'node_uuid': task.node.uuid})
            self._set_step_failed(task, attrs_not_updated)
        else:
            LOG.debug('Verification of BIOS settings for node %(node_uuid)s '
                      'successful.', {'node_uuid': task.node.uuid})

    @task_manager.require_exclusive_lock
    def _reboot(self, task):
        """Reboot the target Redfish service.

        :param task: a TaskManager instance containing the node to act on.
        :raises: InvalidParameterValue when the wrong state is specified
             or the wrong driver info is specified.
        :raises: RedfishError on an error from the Sushy library
        """
        manager_utils.node_power_action(task, states.REBOOT)

    def _set_reboot(self, task):
        """Set driver_internal_info flags for deployment or cleaning reboot.

        :param task: a TaskManager instance containing the node to act on.
        """
        info = task.node.driver_internal_info
        info['post_factory_reset_reboot_requested'] = True
        task.node.driver_internal_info = info
        task.node.save()
        deploy_utils.set_async_step_flags(task.node, reboot=True,
                                          skip_current_step=False)

    def _set_reboot_requested(self, task, attributes):
        """Set driver_internal_info flags for reboot requested.

        :param task: a TaskManager instance containing the node to act on.
        :param attributes: the requested BIOS attributes to update.
        """
        info = task.node.driver_internal_info
        info['post_config_reboot_requested'] = True
        info['requested_bios_attrs'] = attributes
        task.node.driver_internal_info = info
        task.node.save()
        deploy_utils.set_async_step_flags(task.node, reboot=True,
                                          skip_current_step=False)

    def _clear_reboot_requested(self, task):
        """Clear driver_internal_info flags after reboot completed.

        :param task: a TaskManager instance containing the node to act on.
        """
        info = task.node.driver_internal_info
        info.pop('post_config_reboot_requested', None)
        info.pop('post_factory_reset_reboot_requested', None)
        info.pop('requested_bios_attrs', None)
        task.node.driver_internal_info = info
        task.node.save()

    def _set_step_failed(self, task, attrs_not_updated):
        """Fail the cleaning or deployment step and log the error.

        :param task: a TaskManager instance containing the node to act on.
        :param attrs_not_updated: the BIOS attributes that were not updated.
        """
        error_msg = (_('Redfish BIOS apply_configuration step failed for node '
                       '%(node)s. Attributes %(attrs)s are not updated.') %
                     {'node': task.node.uuid, 'attrs': attrs_not_updated})
        last_error = (_('Redfish BIOS apply_configuration step failed. '
                        'Attributes %(attrs)s are not updated.') %
                      {'attrs': attrs_not_updated})
        if task.node.provision_state in [states.CLEANING, states.CLEANWAIT]:
            manager_utils.cleaning_error_handler(task, last_error)
        if task.node.provision_state in [states.DEPLOYING, states.DEPLOYWAIT]:
            manager_utils.deploying_error_handler(task, error_msg, last_error)
