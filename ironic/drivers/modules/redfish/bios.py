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

from oslo_log import log
import sushy

from ironic.common import exception
from ironic.common.i18n import _
from ironic.common import metrics_utils
from ironic.common import states
from ironic.conductor import periodics
from ironic.conductor import utils as manager_utils
from ironic.conf import CONF
from ironic.drivers import base
from ironic.drivers.modules import deploy_utils
from ironic.drivers.modules.redfish import utils as redfish_utils
from ironic import objects

LOG = log.getLogger(__name__)

METRICS = metrics_utils.get_metrics_logger(__name__)

registry_fields = ('attribute_type', 'allowable_values', 'lower_bound',
                   'max_length', 'min_length', 'read_only',
                   'reset_required', 'unique', 'upper_bound')

BIOS_REBOOT_STATES = {
    sushy.BootProgressStates.OS_BOOT_STARTED,
    sushy.BootProgressStates.OS_RUNNING,
}
_DII_STATE = 'redfish_bios_state'
_REBOOT_REQUESTED = 'reboot_requested'
_REQUESTED_BIOS_ATTRS = 'requested_bios_attrs'


class RedfishBIOS(base.BIOSInterface):

    _APPLY_CONFIGURATION_ARGSINFO = {
        'settings': {
            'description': (
                'A list of BIOS settings to be applied'
            ),
            'required': True
        }
    }

    def _parse_allowable_values(self, node, allowable_values):
        """Convert the BIOS registry allowable_value list to expected strings

        :param allowable_values: list of dicts of valid values for enumeration
        :returns: list containing only allowable value names
        """

        # Get name from ValueName if it exists, otherwise use ValueDisplayName
        new_list = []
        for dic in allowable_values:
            key = dic.get('ValueName') or dic.get('ValueDisplayName')
            if key:
                new_list.append(key)
            else:
                LOG.warning('Cannot detect the value name for enumeration '
                            'item %(item)s for node %(node)s',
                            {'item': dic, 'node': node.uuid})

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
                        setting[k] = self._parse_allowable_values(
                            task.node, setting[k])

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

    @base.service_step(priority=0, requires_ramdisk=False)
    @base.clean_step(priority=0, requires_ramdisk=False)
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
        bios_state = info.get(_DII_STATE) or {}
        reboot_requested = bios_state.get(_REBOOT_REQUESTED, False)
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

            self._set_reboot_requested(
                task,
                attributes=None)
            return self.post_reset(task)
        else:
            current_attrs = bios.attributes
            LOG.debug('Post factory reset, BIOS configuration for node '
                      '%(node_uuid)s: %(attrs)r',
                      {'node_uuid': node.uuid, 'attrs': current_attrs})
            self._clear_reboot_requested(task)

    @base.service_step(priority=0, argsinfo=_APPLY_CONFIGURATION_ARGSINFO,
                       requires_ramdisk=False)
    @base.clean_step(priority=0, argsinfo=_APPLY_CONFIGURATION_ARGSINFO,
                     requires_ramdisk=False)
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
        bios_state = info.get(_DII_STATE) or {}
        reboot_requested = bios_state.get(_REBOOT_REQUESTED, False)

        if not reboot_requested:
            self._validate_settings(task, settings)

            # Check if all requested settings already match the current
            # BIOS values.  When a client of the Ironic API re-sends
            # the same request after a successful apply, this avoids an
            # unnecessary reboot cycle.
            current_attrs = bios.attributes or {}
            try:
                pending_attrs = bios.pending_attributes
            except (sushy.exceptions.SushyError, AttributeError):
                pending_attrs = {}
            if not isinstance(pending_attrs, dict):
                pending_attrs = {}
            all_match = True
            for s in settings:
                name, value = s['name'], s['value']
                if current_attrs.get(name) != value:
                    all_match = False
                    break
                if name in pending_attrs:
                    if pending_attrs[name] != value:
                        # A conflicting pending change exists.
                        all_match = False
                        break
            if all_match:
                LOG.info('All requested BIOS settings for node '
                         '%(node_uuid)s already match the current '
                         'values, skipping apply and reboot.',
                         {'node_uuid': task.node.uuid})
                return

            # Step 1: Apply settings and issue a reboot
            LOG.debug('Apply BIOS configuration for node %(node_uuid)s: '
                      '%(settings)r', {'node_uuid': task.node.uuid,
                                       'settings': settings})
            apply_time = None
            try:
                if bios.supported_apply_times and (
                        sushy.APPLY_TIME_ON_RESET in
                        bios.supported_apply_times):
                    apply_time = sushy.APPLY_TIME_ON_RESET
            except AttributeError:
                LOG.warning('SupportedApplyTimes attribute missing for BIOS'
                            ' configuration on node %(node_uuid)s: ',
                            {'node_uuid': task.node.uuid})

            try:
                bios.set_attributes(attributes, apply_time=apply_time)
            except sushy.exceptions.SushyError as e:
                error_msg = (_('Redfish BIOS apply configuration failed for '
                               'node %(node)s. Error: %(error)s') %
                             {'node': task.node.uuid, 'error': e})
                LOG.error(error_msg)
                raise exception.RedfishError(error=error_msg)

            self._set_reboot_requested(
                task,
                attributes)
            return self.post_configuration(task, settings)
        else:
            # Step 2: Verify requested BIOS settings applied
            requested_attrs = (
                bios_state.get(_REQUESTED_BIOS_ATTRS)
                or info.get(_REQUESTED_BIOS_ATTRS))
            LOG.debug('Verify BIOS configuration for node %(node_uuid)s: '
                      '%(attrs)r', {'node_uuid': task.node.uuid,
                                    'attrs': requested_attrs})
            self._clear_reboot_requested(task)
            attrs_not_updated = self._get_unapplied_bios_attrs(
                task, requested_attrs, bios)
            if attrs_not_updated:
                LOG.debug('BIOS settings %(attrs)s for node %(node_uuid)s '
                          'not updated.', {'attrs': attrs_not_updated,
                                           'node_uuid': task.node.uuid})
                self._set_step_failed(task, attrs_not_updated)
            else:
                LOG.debug('Verification of BIOS settings for node '
                          '%(node_uuid)s successful.',
                          {'node_uuid': task.node.uuid})

    def post_reset(self, task):
        """Perform post reset action to apply the BIOS factory reset.

        Extension point to allow vendor implementations to extend this class
        and override this method to perform a custom action to apply the BIOS
        factory reset to the Redfish service. The default implementation
        performs a reboot.

        :param task: a TaskManager instance containing the node to act on.
        """
        return deploy_utils.reboot_to_finish_step(task)

    def post_configuration(self, task, settings):
        """Perform post configuration action to store the BIOS settings.

        Extension point to allow vendor implementations to extend this class
        and override this method to perform a custom action to write the BIOS
        settings to the Redfish service. The default implementation performs
        a reboot.

        :param task: a TaskManager instance containing the node to act on.
        :param settings: a list of BIOS settings to be updated.
        """
        return deploy_utils.reboot_to_finish_step(task)

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

    def _validate_settings(self, task, settings):
        """Validate requested BIOS settings against the cached registry.

        :param task: a TaskManager instance containing the node to act on.
        :param settings: a list of BIOS settings to be validated.
        :raises: InvalidParameterValue if any setting value is invalid
            according to the cached registry, including: read-only settings,
            Enumeration values not in allowable_values, Integer values outside
            lower_bound/upper_bound, and String values outside
            min_length/max_length.
        """
        cached_settings = {
            s.name: s
            for s in objects.BIOSSettingList.get_by_node_id(
                task.context, task.node.id)
        }
        invalid = []
        for s in settings:
            name, value = s['name'], s['value']
            cached = cached_settings.get(name)
            if not cached:
                continue
            if cached.read_only:
                invalid.append(name)
                continue
            if (cached.attribute_type == 'Enumeration'
                    and cached.allowable_values
                    and value not in cached.allowable_values):
                invalid.append(name)
            elif cached.attribute_type == 'Integer':
                try:
                    int_value = int(value)
                except (ValueError, TypeError):
                    invalid.append(name)
                    continue
                if ((cached.lower_bound is not None
                        and int_value < cached.lower_bound)
                        or (cached.upper_bound is not None
                            and int_value > cached.upper_bound)):
                    invalid.append(name)
            elif cached.attribute_type == 'String':
                str_len = len(value)
                if ((cached.min_length is not None
                        and str_len < cached.min_length)
                        or (cached.max_length is not None
                            and str_len > cached.max_length)):
                    invalid.append(name)
        if invalid:
            error_msg = (
                _('Redfish BIOS apply_configuration failed for node '
                  '%(node)s: invalid value for setting(s): %(fields)s') %
                {'node': task.node.uuid,
                 'fields': ', '.join(invalid)})
            LOG.error(error_msg)
            raise exception.InvalidParameterValue(error_msg)

    def _get_unapplied_bios_attrs(self, task, requested_attrs, bios):
        """Return requested BIOS attrs that have not yet been applied.

        :param task: a TaskManager instance containing the node to act on.
        :param requested_attrs: the requested BIOS attributes to update.
        :param bios: BIOS resource object from the system.
        :returns: dict of attributes not yet applied, empty if all applied.
        """
        bios.refresh(force=True)
        current_attrs = bios.attributes
        pending_attrs = bios.pending_attributes
        if not isinstance(pending_attrs, dict):
            pending_attrs = {}
        attrs_not_updated = {}
        for attr in requested_attrs:
            if requested_attrs[attr] != current_attrs.get(attr):
                attrs_not_updated[attr] = requested_attrs[attr]
            elif attr in pending_attrs:
                attrs_not_updated[attr] = requested_attrs[attr]
        return attrs_not_updated

    def _set_reboot_requested(self, task, attributes):
        """Set driver_internal_info flags for reboot requested.

        :param task: a TaskManager instance containing the node to act on.
        :param attributes: the requested BIOS attributes to update.
        """
        node = task.node
        bios_state = {_REBOOT_REQUESTED: True}
        if attributes:
            bios_state[_REQUESTED_BIOS_ATTRS] = attributes
        node.set_driver_internal_info(_DII_STATE, bios_state)
        node.save()
        disable_ramdisk = deploy_utils.is_ramdisk_disabled(node)
        # polling=True tells the IPA heartbeat handler to stand down so
        # that only our periodic task (_query_bios_apply_status) drives
        # step completion.  When ramdisk is active (polling=False), both
        # the heartbeat and the periodic task may race; the exclusive
        # lock in continue_node_clean/deploy/service ensures only one
        # wins.
        deploy_utils.set_async_step_flags(task.node, reboot=True,
                                          skip_current_step=False,
                                          polling=disable_ramdisk)

    def _clear_reboot_requested(self, task):
        """Clear driver_internal_info flags after reboot completed.

        :param task: a TaskManager instance containing the node to act on.
        """
        node = task.node
        node.del_driver_internal_info(_DII_STATE)
        # Drop legacy fields if present from older runs.
        node.del_driver_internal_info('post_bios_reboot_requested')
        node.del_driver_internal_info(_REQUESTED_BIOS_ATTRS)
        node.save()

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
        deploy_utils.step_error_handler(task, error_msg, last_error)

    @METRICS.timer('RedfishBIOS._query_bios_apply_status')
    @periodics.node_periodic(
        purpose='checking async redfish BIOS apply/reset status',
        spacing=CONF.redfish.firmware_update_status_interval,
        filters={'reserved': False,
                 'provision_state_in': {states.CLEANWAIT,
                                        states.SERVICEWAIT,
                                        states.DEPLOYWAIT}},
        predicate_extra_fields=['driver_internal_info'],
        predicate=lambda n: n.driver_internal_info.get(_DII_STATE),
    )
    def _query_bios_apply_status(self, task, manager, context):
        self._check_node_redfish_bios_apply(task)

    @METRICS.timer('RedfishBIOS._check_node_redfish_bios_apply')
    def _check_node_redfish_bios_apply(self, task):
        node = task.node

        bios_state = node.driver_internal_info.get(_DII_STATE) or {}
        if not bios_state:
            LOG.debug('BIOS state cleared for node %(node)s before periodic '
                      'could process it (likely a timeout race).',
                      {'node': node.uuid})
            return

        try:
            system = redfish_utils.get_system(node)
        except (exception.RedfishError,
                exception.RedfishConnectionError,
                sushy.exceptions.SushyError) as e:
            LOG.warning('Unable to query Redfish system for node %(node)s '
                        'while waiting for BIOS reboot completion: '
                        '%(error)s',
                        {'node': node.uuid, 'error': e})
            return

        last_state = system.boot_progress.last_state
        if last_state is not None:
            # BootProgress is reported — touch provisioning to prevent the
            # global timeout from firing while we observe meaningful progress.
            node.touch_provisioning()
            if last_state not in BIOS_REBOOT_STATES:
                LOG.debug('Node %(node)s boot progress: %(state)s. '
                          'Waiting for boot progress to reach OS started.',
                          {'node': node.uuid, 'state': last_state})
                return
        # When BootProgress is unavailable (last_state is None), fall
        # through to the attrs check below. Do NOT touch provisioning
        # so the global timeout remains the safety net.

        requested_attrs = bios_state.get(_REQUESTED_BIOS_ATTRS)
        if requested_attrs:
            attrs_not_updated = self._get_unapplied_bios_attrs(
                task, requested_attrs, system.bios)
            if attrs_not_updated:
                LOG.debug('BIOS settings %(attrs)s for node %(node_uuid)s '
                          'not yet applied; continue polling.',
                          {'attrs': attrs_not_updated,
                           'node_uuid': node.uuid})
                return

        LOG.info('Detected post-BIOS reboot completion for node %(node)s, '
                 'resuming the current step.',
                 {'node': node.uuid})

        if node.clean_step:
            manager_utils.notify_conductor_resume_clean(task)
        elif node.service_step:
            manager_utils.notify_conductor_resume_service(task)
        elif node.deploy_step:
            manager_utils.notify_conductor_resume_deploy(task)
