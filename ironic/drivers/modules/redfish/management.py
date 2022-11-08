# Copyright 2017 Red Hat, Inc.
# All Rights Reserved.
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

import collections
import time
from urllib.parse import urlparse

from ironic_lib import metrics_utils
from oslo_log import log
from oslo_utils import importutils
from oslo_utils import timeutils

from ironic.common import boot_devices
from ironic.common import boot_modes
from ironic.common import components
from ironic.common import exception
from ironic.common.i18n import _
from ironic.common import indicator_states
from ironic.common import states
from ironic.common import utils
from ironic.conductor import periodics
from ironic.conductor import task_manager
from ironic.conductor import utils as manager_utils
from ironic.conf import CONF
from ironic.drivers import base
from ironic.drivers.modules import boot_mode_utils
from ironic.drivers.modules import deploy_utils
from ironic.drivers.modules.redfish import firmware_utils
from ironic.drivers.modules.redfish import utils as redfish_utils

LOG = log.getLogger(__name__)
METRICS = metrics_utils.get_metrics_logger(__name__)

sushy = importutils.try_import('sushy')

BOOT_MODE_CONFIG_INTERVAL = 15

if sushy:
    BOOT_DEVICE_MAP = {
        sushy.BOOT_SOURCE_TARGET_PXE: boot_devices.PXE,
        sushy.BOOT_SOURCE_TARGET_HDD: boot_devices.DISK,
        sushy.BOOT_SOURCE_TARGET_CD: boot_devices.CDROM,
        sushy.BOOT_SOURCE_TARGET_BIOS_SETUP: boot_devices.BIOS
    }

    BOOT_DEVICE_MAP_REV = {v: k for k, v in BOOT_DEVICE_MAP.items()}
    # Previously we used sushy constants in driver_internal_info. This mapping
    # is provided for backward compatibility, taking into account that sushy
    # constants will change from strings to enums.
    BOOT_DEVICE_MAP_REV_COMPAT = dict(
        BOOT_DEVICE_MAP_REV,
        pxe=sushy.BOOT_SOURCE_TARGET_PXE,
        hdd=sushy.BOOT_SOURCE_TARGET_HDD,
        cd=sushy.BOOT_SOURCE_TARGET_CD,
        **{'bios setup': sushy.BOOT_SOURCE_TARGET_BIOS_SETUP}
    )

    BOOT_MODE_MAP = {
        sushy.BOOT_SOURCE_MODE_UEFI: boot_modes.UEFI,
        sushy.BOOT_SOURCE_MODE_BIOS: boot_modes.LEGACY_BIOS
    }

    BOOT_MODE_MAP_REV = {v: k for k, v in BOOT_MODE_MAP.items()}

    BOOT_DEVICE_PERSISTENT_MAP = {
        sushy.BOOT_SOURCE_ENABLED_CONTINUOUS: True,
        sushy.BOOT_SOURCE_ENABLED_ONCE: False
    }

    BOOT_DEVICE_PERSISTENT_MAP_REV = {v: k for k, v in
                                      BOOT_DEVICE_PERSISTENT_MAP.items()}

    INDICATOR_MAP = {
        sushy.INDICATOR_LED_LIT: indicator_states.ON,
        sushy.INDICATOR_LED_OFF: indicator_states.OFF,
        sushy.INDICATOR_LED_BLINKING: indicator_states.BLINKING,
        sushy.INDICATOR_LED_UNKNOWN: indicator_states.UNKNOWN
    }

    INDICATOR_MAP_REV = {
        v: k for k, v in INDICATOR_MAP.items()}


_FIRMWARE_UPDATE_ARGS = {
    'firmware_images': {
        'description': (
            'A list of firmware images to apply.'),
        'required': True
    }}


def _set_boot_device(task, system, device, persistent=False):
    """An internal routine to set the boot device.

    :param task: a task from TaskManager.
    :param system: a Redfish System object.
    :param device: the Redfish boot device.
    :param persistent: Boolean value. True if the boot device will
                       persist to all future boots, False if not.
                       Default: False.
    :raises: SushyError on an error from the Sushy library
    """

    # The BMC handling of the persistent setting is vendor specific.
    # Some vendors require that it not be set if currently equal to
    # desired state (see https://storyboard.openstack.org/#!/story/2007355).
    # Supermicro BMCs handle it in the opposite manner - the
    # persistent setting must be set when setting the boot device
    # (see https://storyboard.openstack.org/#!/story/2008547).
    vendor = task.node.properties.get('vendor', None)
    if vendor and vendor.lower() == 'supermicro':
        enabled = BOOT_DEVICE_PERSISTENT_MAP_REV[persistent]
        LOG.debug('Setting BootSourceOverrideEnable to %(enable)s '
                  'on Supermicro BMC, node %(node)s',
                  {'enable': enabled, 'node': task.node.uuid})
    else:
        desired_enabled = BOOT_DEVICE_PERSISTENT_MAP_REV[persistent]
        current_enabled = system.boot.get('enabled')

        # NOTE(etingof): this can be racy, esp if BMC is not RESTful
        enabled = (desired_enabled
                   if desired_enabled != current_enabled else None)
    try:
        system.set_system_boot_options(device, enabled=enabled)
    except sushy.exceptions.SushyError as e:
        if enabled == sushy.BOOT_SOURCE_ENABLED_CONTINUOUS:
            # NOTE(dtantsur): continuous boot device settings have been
            # removed from Redfish, and some vendors stopped supporting
            # it before an alternative was provided. As a work around,
            # use one-time boot and restore the boot device on every
            # reboot via RedfishPower.
            LOG.debug('Error %(error)s when trying to set a '
                      'persistent boot device on node %(node)s, '
                      'falling back to one-time boot settings',
                      {'error': e, 'node': task.node.uuid})
            system.set_system_boot_options(
                device, enabled=sushy.BOOT_SOURCE_ENABLED_ONCE)
            LOG.warning('Could not set persistent boot device to '
                        '%(dev)s for node %(node)s, using one-time '
                        'boot device instead',
                        {'dev': device, 'node': task.node.uuid})
            utils.set_node_nested_field(
                task.node, 'driver_internal_info',
                'redfish_boot_device', BOOT_DEVICE_MAP[device])
            task.node.save()
        else:
            raise


class RedfishManagement(base.ManagementInterface):

    def __init__(self):
        """Initialize the Redfish management interface.

        :raises: DriverLoadError if the driver can't be loaded due to
            missing dependencies
        """
        super(RedfishManagement, self).__init__()
        if not sushy:
            raise exception.DriverLoadError(
                driver='redfish',
                reason=_('Unable to import the sushy library'))

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

    def get_supported_boot_devices(self, task):
        """Get a list of the supported boot devices.

        :param task: a task from TaskManager.
        :returns: A list with the supported boot devices defined
                  in :mod:`ironic.common.boot_devices`.
        """
        return list(BOOT_DEVICE_MAP_REV)

    @task_manager.require_exclusive_lock
    def restore_boot_device(self, task, system):
        """Restore boot device if needed.

        Checks the redfish_boot_device internal flag and sets the one-time
        boot device accordingly. A warning is issued if it fails.

        This method is supposed to be called from the Redfish power interface
        and should be considered private to the Redfish hardware type.

        :param task: a task from TaskManager.
        :param system: a Redfish System object.
        """
        device = task.node.driver_internal_info.get('redfish_boot_device')
        if not device:
            return

        try:
            # We used to store Redfish constants, now we're storing Ironic
            # values (which is more appropriate). Provide a compatibility layer
            # for already deployed nodes.
            redfish_device = BOOT_DEVICE_MAP_REV_COMPAT[device.lower()]
        except KeyError:
            LOG.error('BUG: unexpected redfish_boot_device %(dev)s for node '
                      '%(node)s', {'dev': device, 'node': task.node.uuid})
            raise

        LOG.debug('Restoring boot device %(dev)s on node %(node)s',
                  {'dev': device, 'node': task.node.uuid})
        try:
            _set_boot_device(task, system, redfish_device)
        except sushy.exceptions.SushyError as e:
            LOG.warning('Unable to recover boot device %(dev)s for node '
                        '%(node)s, relying on the pre-configured boot order. '
                        'Error: %(error)s',
                        {'dev': device, 'node': task.node.uuid, 'error': e})

    @task_manager.require_exclusive_lock
    def set_boot_device(self, task, device, persistent=False):
        """Set the boot device for a node.

        Set the boot device to use on next reboot of the node.

        :param task: a task from TaskManager.
        :param device: the boot device, one of
                       :mod:`ironic.common.boot_devices`.
        :param persistent: Boolean value. True if the boot device will
                           persist to all future boots, False if not.
                           Default: False.
        :raises: InvalidParameterValue on malformed parameter(s)
        :raises: MissingParameterValue on missing parameter(s)
        :raises: RedfishConnectionError when it fails to connect to Redfish
        :raises: RedfishError on an error from the Sushy library
        """
        utils.pop_node_nested_field(
            task.node, 'driver_internal_info', 'redfish_boot_device')
        task.node.save()

        system = redfish_utils.get_system(task.node)

        try:
            _set_boot_device(
                task, system, BOOT_DEVICE_MAP_REV[device],
                persistent=persistent)
        except sushy.exceptions.SushyError as e:
            error_msg = (_('Redfish set boot device failed for node '
                           '%(node)s. Error: %(error)s') %
                         {'node': task.node.uuid, 'error': e})
            LOG.error(error_msg)
            raise exception.RedfishError(error=error_msg)

        # Ensure that boot mode is synced with what is set.
        # Some BMCs reset it to default (BIOS) when changing the boot device.
        # It should only be synced on these vendors as other vendor
        # implementations will result in an error
        # (see https://storyboard.openstack.org/#!/story/2008712)
        vendor = task.node.properties.get('vendor', None)
        if vendor and vendor.lower() == 'supermicro':
            boot_mode_utils.sync_boot_mode(task)

    def get_boot_device(self, task):
        """Get the current boot device for a node.

        :param task: a task from TaskManager.
        :raises: InvalidParameterValue on malformed parameter(s)
        :raises: MissingParameterValue on missing parameter(s)
        :raises: RedfishConnectionError when it fails to connect to Redfish
        :raises: RedfishError on an error from the Sushy library
        :returns: a dictionary containing:

            :boot_device:
                the boot device, one of :mod:`ironic.common.boot_devices` or
                None if it is unknown.
            :persistent:
                Boolean value or None, True if the boot device persists,
                False otherwise. None if it's unknown.


        """
        system = redfish_utils.get_system(task.node)
        return {'boot_device': BOOT_DEVICE_MAP.get(system.boot.get('target')),
                'persistent': BOOT_DEVICE_PERSISTENT_MAP.get(
                    system.boot.get('enabled'))}

    def get_supported_boot_modes(self, task):
        """Get a list of the supported boot modes.

        :param task: A task from TaskManager.
        :returns: A list with the supported boot modes defined
                  in :mod:`ironic.common.boot_modes`. If boot
                  mode support can't be determined, empty list
                  is returned.
        """
        return list(BOOT_MODE_MAP_REV)

    @task_manager.require_exclusive_lock
    def set_boot_mode(self, task, mode):
        """Set the boot mode for a node.

        Set the boot mode to use on next reboot of the node.

        :param task: A task from TaskManager.
        :param mode: The boot mode, one of
                     :mod:`ironic.common.boot_modes`.
        :raises: InvalidParameterValue if an invalid boot mode is
                 specified.
        :raises: MissingParameterValue if a required parameter is missing
        :raises: RedfishConnectionError when it fails to connect to Redfish
        :raises: RedfishError on an error from the Sushy library
        """
        system = redfish_utils.get_system(task.node)

        # NOTE(dtantsur): check the readability of the current mode before
        # modifying anything. I suspect it can become None transiently after
        # the update, while we need to know if it is supported *at all*.
        get_mode_unsupported = (system.boot.get('mode') is None)

        try:
            system.set_system_boot_options(mode=BOOT_MODE_MAP_REV[mode])
        except sushy.exceptions.SushyError as e:
            error_msg = (_('Setting boot mode to %(mode)s '
                           'failed for node %(node)s. '
                           'Error: %(error)s') %
                         {'node': task.node.uuid, 'mode': mode,
                          'error': e})
            LOG.error(error_msg)

            # NOTE(sbaker): Some systems such as HPE Gen9 do not support
            # getting or setting the boot mode. When setting failed and the
            # mode attribute is missing from the boot field, raising
            # UnsupportedDriverExtension will allow the deploy to continue.
            if get_mode_unsupported:
                LOG.info(_('Attempt to set boot mode on node %(node)s '
                           'failed to set boot mode as the node does not '
                           'appear to support overriding the boot mode. '
                           'Possibly partial Redfish implementation?'),
                         {'node': task.node.uuid})
                raise exception.UnsupportedDriverExtension(
                    driver=task.node.driver, extension='set_boot_mode')
            raise exception.RedfishError(error=error_msg)

        # NOTE(dtantsur): this case is rather hypothetical, but in our own
        # emulator, it's possible that mode is constantly set to None, while
        # the request to change the mode succeeds.
        if get_mode_unsupported:
            LOG.warning('The request to set boot mode for node %(node)s to '
                        '%(value)s has succeeded, but the current mode is '
                        'not known. Skipping reboot and assuming '
                        'the operation has succeeded.',
                        {'node': task.node.uuid, 'value': mode})
            return

        self._wait_for_boot_mode(task, system, mode)
        LOG.info('Boot mode for node %(node)s has been set to '
                 '%(value)s', {'node': task.node.uuid, 'value': mode})

    def _wait_for_boot_mode(self, task, system, mode):
        system.refresh(force=True)

        # NOTE(dtantsur/janders): at least Dell machines change boot mode via
        # a BIOS configuration job. A reboot is needed to apply it.
        if system.boot.get('mode') == BOOT_MODE_MAP_REV[mode]:
            LOG.debug('Node %(node)s is already configured with requested '
                      'boot mode %(new_value)s.',
                      {'node': task.node.uuid,
                       'new_value': BOOT_MODE_MAP_REV[mode]})
            return

        LOG.info('Rebooting node %(node)s to change boot mode from '
                 '%(old_value)s to %(new_value)s',
                 {'node': task.node.uuid,
                  'old_value': system.boot.get('mode'),
                  'new_value': BOOT_MODE_MAP_REV[mode]})

        old_power_state = task.driver.power.get_power_state(task)
        manager_utils.node_power_action(task, states.REBOOT)

        if CONF.redfish.boot_mode_config_timeout:
            threshold = time.time() + CONF.redfish.boot_mode_config_timeout
            while (time.time() <= threshold
                   and system.boot.get('mode') != BOOT_MODE_MAP_REV[mode]):
                LOG.debug('Still waiting for boot mode of node %(node)s '
                          'to become %(value)s, current is %(current)s',
                          {'node': task.node.uuid,
                           'value': BOOT_MODE_MAP_REV[mode],
                           'current': system.boot.get('mode')})
                time.sleep(BOOT_MODE_CONFIG_INTERVAL)
                system.refresh(force=True)

            if system.boot.get('mode') != BOOT_MODE_MAP_REV[mode]:
                msg = (_('Timeout reached while waiting for boot mode of '
                         'node %(node)s to become %(value)s, '
                         'current is %(current)s')
                       % {'node': task.node.uuid,
                          'value': BOOT_MODE_MAP_REV[mode],
                          'current': system.boot.get('mode')})
                LOG.error(msg)
                raise exception.RedfishError(error=msg)

        manager_utils.node_power_action(task, old_power_state)

    def get_boot_mode(self, task):
        """Get the current boot mode for a node.

        Provides the current boot mode of the node.

        :param task: A task from TaskManager.
        :raises: MissingParameterValue if a required parameter is missing
        :raises: DriverOperationError or its  derivative in case
                 of driver runtime error.
        :returns: The boot mode, one of :mod:`ironic.common.boot_mode` or
                  None if it is unknown.
        """
        system = redfish_utils.get_system(task.node)

        return BOOT_MODE_MAP.get(system.boot.get('mode'))

    @staticmethod
    def _sensor2dict(resource, *fields):
        return {field: getattr(resource, field)
                for field in fields
                if hasattr(resource, field)}

    @classmethod
    def _get_sensors_fan(cls, chassis):
        """Get fan sensors reading.

        :param chassis: Redfish `chassis` object
        :returns: returns a dict of sensor data.
        """
        sensors = {}

        for fan in chassis.thermal.fans:
            sensor = cls._sensor2dict(
                fan, 'identity', 'max_reading_range',
                'min_reading_range', 'reading', 'reading_units',
                'serial_number', 'physical_context')
            sensor.update(cls._sensor2dict(fan.status, 'state', 'health'))
            unique_name = '%s@%s' % (fan.identity, chassis.identity)
            sensors[unique_name] = sensor

        return sensors

    @classmethod
    def _get_sensors_temperatures(cls, chassis):
        """Get temperature sensors reading.

        :param chassis: Redfish `chassis` object
        :returns: returns a dict of sensor data.
        """
        sensors = {}

        for temps in chassis.thermal.temperatures:
            sensor = cls._sensor2dict(
                temps, 'identity', 'max_reading_range_temp',
                'min_reading_range_temp', 'reading_celsius',
                'physical_context', 'sensor_number')
            sensor.update(cls._sensor2dict(temps.status, 'state', 'health'))
            unique_name = '%s@%s' % (temps.identity, chassis.identity)
            sensors[unique_name] = sensor

        return sensors

    @classmethod
    def _get_sensors_power(cls, chassis):
        """Get power supply sensors reading.

        :param chassis: Redfish `chassis` object
        :returns: returns a dict of sensor data.
        """
        sensors = {}

        for power in chassis.power.power_supplies:
            sensor = cls._sensor2dict(
                power, 'power_capacity_watts',
                'line_input_voltage', 'last_power_output_watts',
                'serial_number')
            sensor.update(cls._sensor2dict(power.status, 'state', 'health'))
            sensor.update(cls._sensor2dict(
                power.input_ranges, 'minimum_voltage',
                'maximum_voltage', 'minimum_frequency_hz',
                'maximum_frequency_hz', 'output_wattage'))
            unique_name = '%s:%s@%s' % (
                power.identity, chassis.power.identity,
                chassis.identity)
            sensors[unique_name] = sensor

        return sensors

    @classmethod
    def _get_sensors_drive(cls, system):
        """Get storage drive sensors reading.

        :param chassis: Redfish `system` object
        :returns: returns a dict of sensor data.
        """
        sensors = {}

        for storage in system.simple_storage.get_members():
            for drive in storage.devices:
                sensor = cls._sensor2dict(
                    drive, 'name', 'model', 'capacity_bytes')
                sensor.update(
                    cls._sensor2dict(drive.status, 'state', 'health'))
                unique_name = '%s:%s@%s' % (
                    drive.name, storage.identity, system.identity)
                sensors[unique_name] = sensor

        return sensors

    def get_sensors_data(self, task):
        """Get sensors data.

        :param task: a TaskManager instance.
        :raises: FailedToGetSensorData when getting the sensor data fails.
        :raises: FailedToParseSensorData when parsing sensor data fails.
        :raises: InvalidParameterValue if required parameters
                 are missing.
        :raises: MissingParameterValue if a required parameter is missing.
        :returns: returns a dict of sensor data grouped by sensor type.
        """
        node = task.node

        sensors = collections.defaultdict(dict)

        system = redfish_utils.get_system(node)

        for chassis in system.chassis:
            try:
                sensors['Fan'].update(self._get_sensors_fan(chassis))

            except sushy.exceptions.SushyError as exc:
                LOG.debug("Failed reading fan information for node "
                          "%(node)s: %(error)s", {'node': node.uuid,
                                                  'error': exc})

            try:
                sensors['Temperature'].update(
                    self._get_sensors_temperatures(chassis))

            except sushy.exceptions.SushyError as exc:
                LOG.debug("Failed reading temperature information for node "
                          "%(node)s: %(error)s", {'node': node.uuid,
                                                  'error': exc})

            try:
                sensors['Power'].update(self._get_sensors_power(chassis))

            except sushy.exceptions.SushyError as exc:
                LOG.debug("Failed reading power information for node "
                          "%(node)s: %(error)s", {'node': node.uuid,
                                                  'error': exc})

        try:
            sensors['Drive'].update(self._get_sensors_drive(system))

        except sushy.exceptions.SushyError as exc:
            LOG.debug("Failed reading drive information for node "
                      "%(node)s: %(error)s", {'node': node.uuid,
                                              'error': exc})

        LOG.debug("Gathered sensor data: %(sensors)s", {'sensors': sensors})

        return sensors

    @task_manager.require_exclusive_lock
    def inject_nmi(self, task):
        """Inject NMI, Non Maskable Interrupt.

        Inject NMI (Non Maskable Interrupt) for a node immediately.

        :param task: A TaskManager instance containing the node to act on.
        :raises: InvalidParameterValue on malformed parameter(s)
        :raises: MissingParameterValue on missing parameter(s)
        :raises: RedfishConnectionError when it fails to connect to Redfish
        :raises: RedfishError on an error from the Sushy library
        """
        system = redfish_utils.get_system(task.node)
        try:
            system.reset_system(sushy.RESET_NMI)
        except sushy.exceptions.SushyError as e:
            error_msg = (_('Redfish inject NMI failed for node %(node)s. '
                           'Error: %(error)s') % {'node': task.node.uuid,
                                                  'error': e})
            LOG.error(error_msg)
            raise exception.RedfishError(error=error_msg)

    def get_supported_indicators(self, task, component=None):
        """Get a map of the supported indicators (e.g. LEDs).

        :param task: A task from TaskManager.
        :param component: If not `None`, return indicator information
            for just this component, otherwise return indicators for
            all existing components.
        :returns: A dictionary of hardware components
            (:mod:`ironic.common.components`) as keys with values
            being dictionaries having indicator IDs as keys and indicator
            properties as values.

            ::

             {
                 'chassis': {
                     'enclosure-0': {
                         "readonly": true,
                         "states": [
                             "OFF",
                             "ON"
                         ]
                     }
                 },
                 'system':
                     'blade-A': {
                         "readonly": true,
                         "states": [
                             "OFF",
                             "ON"
                         ]
                     }
                 },
                 'drive':
                     'ssd0': {
                         "readonly": true,
                         "states": [
                             "OFF",
                             "ON"
                         ]
                     }
                 }
             }
        """
        properties = {
            "readonly": False,
            "states": [
                indicator_states.BLINKING,
                indicator_states.OFF,
                indicator_states.ON
            ]
        }

        indicators = {}

        system = redfish_utils.get_system(task.node)

        try:
            if component in (None, components.CHASSIS) and system.chassis:
                indicators[components.CHASSIS] = {
                    chassis.uuid: properties for chassis in system.chassis
                    if chassis.indicator_led
                }

        except sushy.exceptions.SushyError as e:
            LOG.debug('Chassis indicator not available for node %(node)s: '
                      '%(error)s', {'node': task.node.uuid, 'error': e})

        try:
            if component in (None, components.SYSTEM) and system.indicator_led:
                indicators[components.SYSTEM] = {
                    system.uuid: properties
                }

        except sushy.exceptions.SushyError as e:
            LOG.debug('System indicator not available for node %(node)s: '
                      '%(error)s', {'node': task.node.uuid, 'error': e})

        try:
            if (component in (None, components.DISK)
                    and system.simple_storage
                    and system.simple_storage.drives):
                indicators[components.DISK] = {
                    drive.uuid: properties
                    for drive in system.simple_storage.drives
                    if drive.indicator_led
                }

        except sushy.exceptions.SushyError as e:
            LOG.debug('Drive indicator not available for node %(node)s: '
                      '%(error)s', {'node': task.node.uuid, 'error': e})

        return indicators

    def set_indicator_state(self, task, component, indicator, state):
        """Set indicator on the hardware component to the desired state.

        :param task: A task from TaskManager.
        :param component: The hardware component, one of
            :mod:`ironic.common.components`.
        :param indicator: Indicator ID (as reported by
            `get_supported_indicators`).
        :param state: Desired state of the indicator, one of
            :mod:`ironic.common.indicator_states`.
        :raises: InvalidParameterValue if an invalid component, indicator
                 or state is specified.
        :raises: MissingParameterValue if a required parameter is missing
        :raises: RedfishError on an error from the Sushy library
        """
        system = redfish_utils.get_system(task.node)

        try:
            if (component == components.SYSTEM
                    and indicator == system.uuid):
                system.set_indicator_led(INDICATOR_MAP_REV[state])
                return

            elif (component == components.CHASSIS
                    and system.chassis):
                for chassis in system.chassis:
                    if chassis.uuid == indicator:
                        chassis.set_indicator_led(
                            INDICATOR_MAP_REV[state])
                        return

            elif (component == components.DISK
                  and system.simple_storage
                  and system.simple_storage.drives):
                for drive in system.simple_storage.drives:
                    if drive.uuid == indicator:
                        drive.set_indicator_led(
                            INDICATOR_MAP_REV[state])
                        return

        except sushy.exceptions.SushyError as e:
            error_msg = (_('Redfish set %(component)s indicator %(indicator)s '
                           'state %(state)s failed for node %(node)s. Error: '
                           '%(error)s') % {'component': component,
                                           'indicator': indicator,
                                           'state': state,
                                           'node': task.node.uuid,
                                           'error': e})
            LOG.error(error_msg)
            raise exception.RedfishError(error=error_msg)

        raise exception.MissingParameterValue(_(
            "Unknown indicator %(indicator)s for component %(component)s of "
            "node %(uuid)s") % {'indicator': indicator,
                                'component': component,
                                'uuid': task.node.uuid})

    def get_indicator_state(self, task, component, indicator):
        """Get current state of the indicator of the hardware component.

        :param task: A task from TaskManager.
        :param component: The hardware component, one of
            :mod:`ironic.common.components`.
        :param indicator: Indicator ID (as reported by
            `get_supported_indicators`).
        :raises: MissingParameterValue if a required parameter is missing
        :raises: RedfishError on an error from the Sushy library
        :returns: Current state of the indicator, one of
            :mod:`ironic.common.indicator_states`.
        """
        system = redfish_utils.get_system(task.node)

        try:
            if (component == components.SYSTEM
                    and indicator == system.uuid):
                return INDICATOR_MAP[system.indicator_led]

            if (component == components.CHASSIS
                    and system.chassis):
                for chassis in system.chassis:
                    if chassis.uuid == indicator:
                        return INDICATOR_MAP[chassis.indicator_led]

            if (component == components.DISK
                    and system.simple_storage
                    and system.simple_storage.drives):
                for drive in system.simple_storage.drives:
                    if drive.uuid == indicator:
                        return INDICATOR_MAP[drive.indicator_led]

        except sushy.exceptions.SushyError as e:
            error_msg = (_('Redfish get %(component)s indicator %(indicator)s '
                           'state failed for node %(node)s. Error: '
                           '%(error)s') % {'component': component,
                                           'indicator': indicator,
                                           'node': task.node.uuid,
                                           'error': e})
            LOG.error(error_msg)
            raise exception.RedfishError(error=error_msg)

        raise exception.MissingParameterValue(_(
            "Unknown indicator %(indicator)s for component %(component)s of "
            "node %(uuid)s") % {'indicator': indicator,
                                'component': component,
                                'uuid': task.node.uuid})

    def detect_vendor(self, task):
        """Detects and returns the hardware vendor.

        Uses the System's Manufacturer field.

        :param task: A task from TaskManager.
        :raises: InvalidParameterValue if an invalid component, indicator
            or state is specified.
        :raises: MissingParameterValue if a required parameter is missing
        :raises: RedfishError on driver-specific problems.
        :returns: String representing the BMC reported Vendor or
                  Manufacturer, otherwise returns None.
        """
        return redfish_utils.get_system(task.node).manufacturer

    @METRICS.timer('RedfishManagement.update_firmware')
    @base.clean_step(priority=0, abortable=False,
                     argsinfo=_FIRMWARE_UPDATE_ARGS)
    @base.service_step(priority=0, abortable=False,
                       argsinfo=_FIRMWARE_UPDATE_ARGS)
    def update_firmware(self, task, firmware_images):
        """Updates the firmware on the node.

        :param task: a TaskManager instance containing the node to act on.
        :param firmware_images: A list of firmware images are to apply.
        :returns: None if it is completed.
        :raises: RedfishError on an error from the Sushy library.
        """
        firmware_utils.validate_update_firmware_args(firmware_images)
        node = task.node

        LOG.debug('Updating firmware on node %(node_uuid)s with firmware '
                  '%(firmware_images)s',
                  {'node_uuid': node.uuid,
                   'firmware_images': firmware_images})

        update_service = redfish_utils.get_update_service(task.node)

        # The cleaning infrastructure has an exclusive lock on the node, so
        # there is no need to get one here.
        self._apply_firmware_update(node, update_service, firmware_images)

        # set_async_step_flags calls node.save()
        deploy_utils.set_async_step_flags(
            node,
            reboot=True,
            skip_current_step=True,
            polling=True)

        return deploy_utils.reboot_to_finish_step(task)

    def _apply_firmware_update(self, node, update_service, firmware_updates):
        """Applies the next firmware update to the node

        Applies the first firmware update in the firmware_updates list to
        the node.

        Note that the caller must have an exclusive lock on the node and
        the caller must ensure node.save() is called after making this
        call.

        :param node: the node to apply the next update to
        :param update_service: the sushy firmware update service
        :param firmware_updates: the remaining firmware updates to apply
        """

        firmware_update = firmware_updates[0]
        firmware_url, need_cleanup = self._stage_firmware_file(
            node, firmware_update)

        LOG.debug('Applying firmware %(firmware_image)s to node '
                  '%(node_uuid)s',
                  {'firmware_image': firmware_url,
                   'node_uuid': node.uuid})

        task_monitor = update_service.simple_update(firmware_url)

        firmware_update['task_monitor'] = task_monitor.task_monitor_uri
        node.set_driver_internal_info('firmware_updates', firmware_updates)

        if need_cleanup:
            fw_cleanup = node.driver_internal_info.get('firmware_cleanup')
            if not fw_cleanup:
                fw_cleanup = [need_cleanup]
            elif need_cleanup not in fw_cleanup:
                fw_cleanup.append(need_cleanup)
            node.set_driver_internal_info('firmware_cleanup', fw_cleanup)

    def _continue_firmware_updates(self, task, update_service,
                                   firmware_updates):
        """Continues processing the firmware updates

        Continues to process the firmware updates on the node.

        Note that the caller must have an exclusive lock on the node.

        :param task: a TaskManager instance containing the node to act on.
        :param update_service: the sushy firmware update service
        :param firmware_updates: the remaining firmware updates to apply
        """

        node = task.node
        firmware_update = firmware_updates[0]
        wait_interval = firmware_update.get('wait')
        if wait_interval:
            time_now = str(timeutils.utcnow().isoformat())
            firmware_update['wait_start_time'] = time_now

            LOG.debug('Waiting at %(time)s for %(seconds)s seconds after '
                      'firmware update %(firmware_image)s on node %(node)s',
                      {'time': time_now,
                       'seconds': wait_interval,
                       'firmware_image': firmware_update['url'],
                       'node': node.uuid})

            node.set_driver_internal_info('firmware_updates',
                                          firmware_updates)
            node.save()
            return

        if len(firmware_updates) == 1:
            self._clear_firmware_updates(node)

            LOG.info('Firmware updates completed for node %(node)s',
                     {'node': node.uuid})

            manager_utils.notify_conductor_resume_clean(task)
        else:
            firmware_updates.pop(0)
            self._apply_firmware_update(node,
                                        update_service,
                                        firmware_updates)
            node.save()
            manager_utils.node_power_action(task, states.REBOOT)

    def _clear_firmware_updates(self, node):
        """Clears firmware updates artifacts

        Clears firmware updates from driver_internal_info and any files
        that were staged.

        Note that the caller must have an exclusive lock on the node.

        :param node: the node to clear the firmware updates from
        """
        firmware_utils.cleanup(node)
        node.del_driver_internal_info('firmware_updates')
        node.del_driver_internal_info('firmware_cleanup')
        node.save()

    @METRICS.timer('RedfishManagement._query_firmware_update_failed')
    @periodics.node_periodic(
        purpose='checking if async firmware update failed',
        spacing=CONF.redfish.firmware_update_fail_interval,
        filters={'reserved': False, 'provision_state': states.CLEANFAIL,
                 'maintenance': True},
        predicate_extra_fields=['driver_internal_info'],
        predicate=lambda n: n.driver_internal_info.get('firmware_updates'),
    )
    def _query_firmware_update_failed(self, task, manager, context):
        """Periodic job to check for failed firmware updates."""
        # A firmware update failed. Discard any remaining firmware
        # updates so when the user takes the node out of
        # maintenance mode, pending firmware updates do not
        # automatically continue.
        LOG.warning('Firmware update failed for node %(node)s. '
                    'Discarding remaining firmware updates.',
                    {'node': task.node.uuid})

        task.upgrade_lock()
        self._clear_firmware_updates(task.node)

    @METRICS.timer('RedfishManagement._query_firmware_update_status')
    @periodics.node_periodic(
        purpose='checking async firmware update tasks',
        spacing=CONF.redfish.firmware_update_status_interval,
        filters={'reserved': False, 'provision_state': states.CLEANWAIT},
        predicate_extra_fields=['driver_internal_info'],
        predicate=lambda n: n.driver_internal_info.get('firmware_updates'),
    )
    def _query_firmware_update_status(self, task, manager, context):
        """Periodic job to check firmware update tasks."""
        self._check_node_firmware_update(task)

    @METRICS.timer('RedfishManagement._check_node_firmware_update')
    def _check_node_firmware_update(self, task):
        """Check the progress of running firmware update on a node."""

        node = task.node

        firmware_updates = node.driver_internal_info['firmware_updates']
        current_update = firmware_updates[0]

        try:
            update_service = redfish_utils.get_update_service(node)
        except exception.RedfishConnectionError as e:
            # If the BMC firmware is being updated, the BMC will be
            # unavailable for some amount of time.
            LOG.warning('Unable to communicate with firmware update service '
                        'on node %(node)s. Will try again on the next poll. '
                        'Error: %(error)s',
                        {'node': node.uuid,
                         'error': e})
            return

        wait_start_time = current_update.get('wait_start_time')
        if wait_start_time:
            wait_start = timeutils.parse_isotime(wait_start_time)

            elapsed_time = timeutils.utcnow(True) - wait_start
            if elapsed_time.seconds >= current_update['wait']:
                LOG.debug('Finished waiting after firmware update '
                          '%(firmware_image)s on node %(node)s. '
                          'Elapsed time: %(seconds)s seconds',
                          {'firmware_image': current_update['url'],
                           'node': node.uuid,
                           'seconds': elapsed_time.seconds})
                current_update.pop('wait', None)
                current_update.pop('wait_start_time', None)

                task.upgrade_lock()
                self._continue_firmware_updates(task,
                                                update_service,
                                                firmware_updates)
            else:
                LOG.debug('Continuing to wait after firmware update '
                          '%(firmware_image)s on node %(node)s. '
                          'Elapsed time: %(seconds)s seconds',
                          {'firmware_image': current_update['url'],
                           'node': node.uuid,
                           'seconds': elapsed_time.seconds})

            return

        try:
            task_monitor = redfish_utils.get_task_monitor(
                node, current_update['task_monitor'])
        except exception.RedfishError:
            # The BMC deleted the Task before we could query it
            LOG.warning('Firmware update completed for node %(node)s, '
                        'firmware %(firmware_image)s, but success of the '
                        'update is unknown.  Assuming update was successful.',
                        {'node': node.uuid,
                         'firmware_image': current_update['url']})
            task.upgrade_lock()
            self._continue_firmware_updates(task,
                                            update_service,
                                            firmware_updates)
            return

        if not task_monitor.is_processing:
            # The last response does not necessarily contain a Task,
            # so get it
            sushy_task = task_monitor.get_task()

            # Only parse the messages if the BMC did not return parsed
            # messages
            messages = []
            if sushy_task.messages and not sushy_task.messages[0].message:
                sushy_task.parse_messages()

            messages = [m.message for m in sushy_task.messages]

            if (sushy_task.task_state == sushy.TASK_STATE_COMPLETED
                    and sushy_task.task_status in
                    [sushy.HEALTH_OK, sushy.HEALTH_WARNING]):
                LOG.info('Firmware update succeeded for node %(node)s, '
                         'firmware %(firmware_image)s: %(messages)s',
                         {'node': node.uuid,
                          'firmware_image': current_update['url'],
                          'messages': ", ".join(messages)})

                task.upgrade_lock()
                self._continue_firmware_updates(task,
                                                update_service,
                                                firmware_updates)
            else:
                error_msg = (_('Firmware update failed for node %(node)s, '
                               'firmware %(firmware_image)s. '
                               'Error: %(errors)s') %
                             {'node': node.uuid,
                              'firmware_image': current_update['url'],
                              'errors': ",  ".join(messages)})

                task.upgrade_lock()
                self._clear_firmware_updates(node)
                manager_utils.cleaning_error_handler(task, error_msg)
        else:
            LOG.debug('Firmware update in progress for node %(node)s, '
                      'firmware %(firmware_image)s.',
                      {'node': node.uuid,
                       'firmware_image': current_update['url']})

    def _stage_firmware_file(self, node, firmware_update):
        """Stage firmware update according to configuration.

        :param node: Node for which to stage the firmware file
        :param firmware_update: Firmware update to stage
        :returns: Tuple of staged URL and source that needs cleanup of
            staged files afterwards. If not staging, then return
            original URL and None for source that needs cleanup.
        :raises IronicException: If something goes wrong with staging.
        """
        try:
            url = firmware_update['url']
            parsed_url = urlparse(url)
            scheme = parsed_url.scheme.lower()
            source = (firmware_update.get('source')
                      or CONF.redfish.firmware_source).lower()

            # Keep it simple, in further processing TLS does not matter
            if scheme == 'https':
                scheme = 'http'

            # If source and scheme is HTTP, then no staging,
            # returning original location
            if scheme == 'http' and source == scheme:
                LOG.debug('For node %(node)s serving firmware from original '
                          'location %(url)s', {'node': node.uuid, 'url': url})
                return url, None

            # If source and scheme is Swift, then not moving, but
            # returning Swift temp URL
            if scheme == 'swift' and source == scheme:
                temp_url = firmware_utils.get_swift_temp_url(parsed_url)
                LOG.debug('For node %(node)s serving original firmware at '
                          '%(url)s via Swift temporary url %(temp_url)s',
                          {'node': node.uuid, 'url': url,
                           'temp_url': temp_url})
                return temp_url, None

            # For remaining, download the image to temporary location
            temp_file = firmware_utils.download_to_temp(node, url)

            firmware_utils.verify_checksum(
                node, firmware_update.get('checksum'), temp_file)

            return firmware_utils.stage(node, source, temp_file)

        except exception.IronicException as error:
            firmware_utils.cleanup(node)
            raise error

    def get_secure_boot_state(self, task):
        """Get the current secure boot state for the node.

        :param task: A task from TaskManager.
        :raises: MissingParameterValue if a required parameter is missing
        :raises: RedfishError or its derivative in case of a driver
            runtime error.
        :raises: UnsupportedDriverExtension if secure boot is
                 not supported by the hardware.
        :returns: Boolean
        """
        system = redfish_utils.get_system(task.node)
        try:
            return system.secure_boot.enabled
        except sushy.exceptions.MissingAttributeError:
            raise exception.UnsupportedDriverExtension(
                driver=task.node.driver, extension='get_secure_boot_state')

    def set_secure_boot_state(self, task, state):
        """Set the current secure boot state for the node.

        :param task: A task from TaskManager.
        :param state: A new state as a boolean.
        :raises: MissingParameterValue if a required parameter is missing
        :raises: RedfishError or its derivative in case of a driver
            runtime error.
        :raises: UnsupportedDriverExtension if secure boot is
                 not supported by the hardware.
        """
        system = redfish_utils.get_system(task.node)
        try:
            sb = system.secure_boot
        except sushy.exceptions.MissingAttributeError:
            LOG.error('Secure boot has been requested for node %s but its '
                      'Redfish BMC does not have a SecureBoot object',
                      task.node.uuid)
            raise exception.UnsupportedDriverExtension(
                driver=task.node.driver, extension='set_secure_boot_state')

        if sb.enabled == state:
            LOG.info('Secure boot state for node %(node)s is already '
                     '%(value)s', {'node': task.node.uuid, 'value': state})
            return

        boot_mode = system.boot.get('mode')
        if boot_mode == sushy.BOOT_SOURCE_MODE_BIOS:
            # NOTE(dtantsur): the case of disabling secure boot when boot mode
            # is legacy should be covered by the check above.
            msg = (_("Configuring secure boot requires UEFI for node %s")
                   % task.node.uuid)
            LOG.error(msg)
            raise exception.RedfishError(error=msg)

        try:
            sb.set_enabled(state)
        except sushy.exceptions.SushyError as exc:
            msg = (_('Failed to set secure boot state on node %(node)s to '
                     '%(value)s: %(exc)s')
                   % {'node': task.node.uuid, 'value': state, 'exc': exc})
            LOG.error(msg)
            raise exception.RedfishError(error=msg)

        self._wait_for_secure_boot(task, sb, state)
        LOG.info('Secure boot state for node %(node)s has been set to '
                 '%(value)s', {'node': task.node.uuid, 'value': state})

    def _wait_for_secure_boot(self, task, sb, state):
        # NOTE(dtantsur): at least Dell machines change secure boot status via
        # a BIOS configuration job. A reboot is needed to apply it.
        sb.refresh(force=True)
        if sb.enabled == state:
            return

        LOG.info('Rebooting node %(node)s to change secure boot state to '
                 '%(value)s', {'node': task.node.uuid, 'value': state})

        old_power_state = task.driver.power.get_power_state(task)
        manager_utils.node_power_action(task, states.REBOOT)

        if CONF.redfish.boot_mode_config_timeout:
            threshold = time.time() + CONF.redfish.boot_mode_config_timeout
            while time.time() <= threshold and sb.enabled != state:
                LOG.debug(
                    'Still waiting for secure boot state of node %(node)s '
                    'to become %(value)s, current is %(current)s',
                    {'node': task.node.uuid, 'value': state,
                     'current': sb.enabled})
                time.sleep(BOOT_MODE_CONFIG_INTERVAL)
                sb.refresh(force=True)

            if sb.enabled != state:
                msg = (_('Timeout reached while waiting for secure boot state '
                         'of node %(node)s to become %(state)s, '
                         'current is %(current)s')
                       % {'node': task.node.uuid, 'state': state,
                          'current': sb.enabled})
                LOG.error(msg)
                raise exception.RedfishError(error=msg)

        manager_utils.node_power_action(task, old_power_state)

    def _reset_keys(self, task, reset_type):
        system = redfish_utils.get_system(task.node)
        try:
            sb = system.secure_boot
        except sushy.exceptions.MissingAttributeError:
            LOG.error('Resetting secure boot keys has been requested for node '
                      '%s but its Redfish BMC does not have a SecureBoot '
                      'object', task.node.uuid)
            raise exception.UnsupportedDriverExtension(
                driver=task.node.driver, extension='reset_keys')

        try:
            sb.reset_keys(reset_type)
        except sushy.exceptions.SushyError as exc:
            msg = (_('Failed to reset secure boot keys on node %(node)s: '
                     '%(exc)s')
                   % {'node': task.node.uuid, 'exc': exc})
            LOG.error(msg)
            raise exception.RedfishError(error=msg)

    @METRICS.timer('RedfishManagement.reset_secure_boot_keys_to_default')
    @base.deploy_step(priority=0)
    @base.clean_step(priority=0)
    def reset_secure_boot_keys_to_default(self, task):
        """Reset secure boot keys to manufacturing defaults.

        :param task: a task from TaskManager.
        :raises: UnsupportedDriverExtension if secure boot is now supported.
        :raises: RedfishError on runtime driver error.
        """
        self._reset_keys(task, sushy.SECURE_BOOT_RESET_KEYS_TO_DEFAULT)
        LOG.info('Secure boot keys have been reset to their defaults on '
                 'node %s', task.node.uuid)

    @METRICS.timer('RedfishManagement.clear_secure_boot_keys')
    @base.deploy_step(priority=0)
    @base.clean_step(priority=0)
    def clear_secure_boot_keys(self, task):
        """Clear all secure boot keys.

        :param task: a task from TaskManager.
        :raises: UnsupportedDriverExtension if secure boot is now supported.
        :raises: RedfishError on runtime driver error.
        """
        self._reset_keys(task, sushy.SECURE_BOOT_RESET_KEYS_DELETE_ALL)
        LOG.info('Secure boot keys have been removed from node %s',
                 task.node.uuid)

    def get_mac_addresses(self, task):
        """Get MAC address information for the node.

        :param task: A TaskManager instance containing the node to act on.
        :raises: RedfishConnectionError when it fails to connect to Redfish
        :raises: RedfishError on an error from the Sushy library
        :returns: A list of MAC addresses for the node
        """
        system = redfish_utils.get_system(task.node)
        try:
            return list(redfish_utils.get_enabled_macs(task, system))
        # NOTE(janders) we should handle MissingAttributeError separately
        # from other SushyErrors - some servers (e.g. some Cisco UCSB and UCSX
        # blades) are missing EthernetInterfaces attribute yet could be
        # provisioned successfully if MAC information is provided manually AND
        # this exception is caught and handled accordingly.
        except sushy.exceptions.MissingAttributeError as exc:
            LOG.warning('Cannot get MAC addresses for node %(node)s: %(exc)s',
                        {'node': task.node.uuid, 'exc': exc})
        # if the exception is not a MissingAttributeError, raise it
        except sushy.exceptions.SushyError as exc:
            msg = (_('Failed to get network interface information on node '
                     '%(node)s: %(exc)s')
                   % {'node': task.node.uuid, 'exc': exc})
            LOG.error(msg)
            raise exception.RedfishError(error=msg)
