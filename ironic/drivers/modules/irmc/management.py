# Copyright 2015 FUJITSU LIMITED
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
iRMC Management Driver
"""

from ironic_lib import metrics_utils
from oslo_log import log as logging
from oslo_utils import importutils

from ironic.common import boot_devices
from ironic.common import exception
from ironic.common.i18n import _
from ironic.common import states
from ironic.conductor import task_manager
from ironic.conductor import utils as manager_utils
from ironic import conf
from ironic.drivers import base
from ironic.drivers.modules import boot_mode_utils
from ironic.drivers.modules import ipmitool
from ironic.drivers.modules.irmc import common as irmc_common

irmc = importutils.try_import('scciclient.irmc')

LOG = logging.getLogger(__name__)
CONF = conf.CONF

METRICS = metrics_utils.get_metrics_logger(__name__)

# Boot Option Parameters #5 Data2 defined in
# Set/Get System Boot Options Command, IPMI spec v2.0.
_BOOTPARAM5_DATA2 = {boot_devices.PXE: '0x04',
                     boot_devices.DISK: '0x08',
                     # note (naohirot)
                     # boot_devices.CDROM is tentatively set to '0x20' rather
                     # than '0x14' as a work-around to force iRMC vmedia boot.
                     #   0x14 = Force boot from default CD/DVD
                     #   0x20 = Force boot from remotely connected CD/DVD
                     boot_devices.CDROM: '0x20',
                     boot_devices.BIOS: '0x18',
                     boot_devices.SAFE: '0x0c',
                     }


def _get_sensors_data(task):
    """Get sensors data method.

    It gets sensor data from the task's node via SCCI, and convert the data
    from XML to the dict format.

    :param task: A TaskManager instance.
    :raises: FailedToGetSensorData when getting the sensor data fails.
    :returns: Returns a consistent formatted dict of sensor data grouped
              by sensor type, which can be processed by Ceilometer.
    """

    try:
        report = irmc_common.get_irmc_report(task.node)
        sensor = irmc.scci.get_sensor_data(report)

    except (exception.InvalidParameterValue,
            exception.MissingParameterValue,
            irmc.scci.SCCIInvalidInputError,
            irmc.scci.SCCIClientError) as e:
        LOG.error("SCCI get sensor data failed for node %(node_id)s "
                  "with the following error: %(error)s",
                  {'node_id': task.node.uuid, 'error': e})
        raise exception.FailedToGetSensorData(
            node=task.node.uuid, error=e)

    sensors_data = {}
    for sdr in sensor:
        sensor_type_name = sdr.find('./Data/Decoded/Sensor/TypeName')
        sensor_type_number = sdr.find('./Data/Decoded/Sensor/Type')
        entity_name = sdr.find('./Data/Decoded/Entity/Name')
        entity_id = sdr.find('./Data/Decoded/Entity/ID')

        if None in (sensor_type_name, sensor_type_number,
                    entity_name, entity_id):
            continue

        sensor_type = ('%s (%s)' %
                       (sensor_type_name.text, sensor_type_number.text))
        sensor_id = ('%s (%s)' %
                     (entity_name.text, entity_id.text))
        reading_value = sdr.find(
            './Data/Decoded/Sensor/Thresholds/*/Normalized')
        reading_value_text = "None" if (
            reading_value is None) else str(reading_value.text)
        reading_units = sdr.find('./Data/Decoded/Sensor/BaseUnitName')
        reading_units_text = "None" if (
            reading_units is None) else str(reading_units.text)
        sensor_reading = '%s %s' % (reading_value_text, reading_units_text)

        sensors_data.setdefault(sensor_type, {})[sensor_id] = {
            'Sensor Reading': sensor_reading,
            'Sensor ID': sensor_id,
            'Units': reading_units_text,
        }

    return sensors_data


def backup_bios_config(task):
    """Backup BIOS config from a node.

    :param task: a TaskManager instance containing the node to act on.
    :raises: IRMCOperationError on failure.
    """
    node_uuid = task.node.uuid

    # Skip this operation if the clean step 'restore' is disabled
    if CONF.irmc.clean_priority_restore_irmc_bios_config == 0:
        LOG.debug('Skipped the operation backup_BIOS_config for node %s '
                  'as the clean step restore_BIOS_config is disabled.',
                  node_uuid)
        return

    irmc_info = irmc_common.parse_driver_info(task.node)

    try:
        # Backup bios config
        result = irmc.elcm.backup_bios_config(irmc_info)
    except irmc.scci.SCCIError as e:
        LOG.error('Failed to backup BIOS config for node %(node)s. '
                  'Error: %(error)s', {'node': node_uuid, 'error': e})
        raise exception.IRMCOperationError(operation='backup BIOS config',
                                           error=e)

    # Save bios config into the driver_internal_info
    task.node.set_driver_internal_info('irmc_bios_config',
                                       result['bios_config'])
    task.node.save()

    LOG.info('BIOS config is backed up successfully for node %s',
             node_uuid)

    # NOTE(tiendc): When the backup operation done, server is automatically
    # shutdown. However, this function is called right before the method
    # task.driver.deploy() that will trigger a reboot. So, we don't need
    # to power on the server at this point.


def _restore_bios_config(task):
    """Restore BIOS config to a node.

    :param task: a TaskManager instance containing the node to act on.
    :raises: IRMCOperationError if the operation fails.
    """
    node_uuid = task.node.uuid

    # Get bios config stored in the node object
    bios_config = task.node.driver_internal_info.get('irmc_bios_config')
    if not bios_config:
        LOG.info('Skipped operation "restore BIOS config" on node %s '
                 'as the backup data not found.', node_uuid)
        return

    def _remove_bios_config(task, reboot_flag=False):
        """Remove backup bios config from the node."""
        task.node.del_driver_internal_info('irmc_bios_config')
        # NOTE(tiendc): If reboot flag is raised, then the BM will
        # reboot and cause a bug if the next clean step is in-band.
        # See https://storyboard.openstack.org/#!/story/2002731
        if reboot_flag:
            task.node.set_driver_internal_info('cleaning_reboot', True)
        task.node.save()

    irmc_info = irmc_common.parse_driver_info(task.node)

    try:
        # Restore bios config
        irmc.elcm.restore_bios_config(irmc_info, bios_config)
    except irmc.scci.SCCIError as e:
        # If the input bios config is not correct or corrupted, then
        # we should remove it from the node object.
        if isinstance(e, irmc.scci.SCCIInvalidInputError):
            _remove_bios_config(task)

        LOG.error('Failed to restore BIOS config on node %(node)s. '
                  'Error: %(error)s', {'node': node_uuid, 'error': e})
        raise exception.IRMCOperationError(operation='restore BIOS config',
                                           error=e)

    # Remove the backup data after restoring
    _remove_bios_config(task, reboot_flag=True)

    LOG.info('BIOS config is restored successfully on node %s',
             node_uuid)

    # Change power state to ON as server is automatically
    # shutdown after the operation.
    manager_utils.node_power_action(task, states.POWER_ON)


class IRMCManagement(ipmitool.IPMIManagement):

    def get_properties(self):
        """Return the properties of the interface.

        :returns: Dictionary of <property name>:<property description> entries.
        """
        return irmc_common.COMMON_PROPERTIES

    @METRICS.timer('IRMCManagement.validate')
    def validate(self, task):
        """Validate the driver-specific management information.

        This method validates whether the 'driver_info' property of the
        supplied node contains the required information for this driver.

        :param task: A TaskManager instance containing the node to act on.
        :raises: InvalidParameterValue if required parameters are invalid.
        :raises: MissingParameterValue if a required parameter is missing.
        """
        irmc_common.parse_driver_info(task.node)
        irmc_common.update_ipmi_properties(task)
        super(IRMCManagement, self).validate(task)

    @METRICS.timer('IRMCManagement.set_boot_device')
    @task_manager.require_exclusive_lock
    def set_boot_device(self, task, device, persistent=False):
        """Set the boot device for a node.

        Set the boot device to use on next reboot of the node.

        :param task: A task from TaskManager.
        :param device: The boot device, one of the supported devices
                       listed in :mod:`ironic.common.boot_devices`.
        :param persistent: Boolean value. True if the boot device will
                           persist to all future boots, False if not.
                           Default: False.
        :raises: InvalidParameterValue if an invalid boot device is
                 specified.
        :raises: MissingParameterValue if a required parameter is missing.
        :raises: IPMIFailure on an error from ipmitool.

        """
        if device not in self.get_supported_boot_devices(task):
            raise exception.InvalidParameterValue(_(
                "Invalid boot device %s specified.") % device)

        uefi_mode = (
            boot_mode_utils.get_boot_mode(task.node) == 'uefi')

        # disable 60 secs timer
        timeout_disable = "0x00 0x08 0x03 0x08"
        ipmitool.send_raw(task, timeout_disable)

        # note(naohirot):
        # Set System Boot Options : ipmi cmd '0x08', bootparam '0x05'
        #
        # $ ipmitool raw 0x00 0x08 0x05 data1 data2 0x00 0x00 0x00
        #
        # data1 : '0xe0' persistent + uefi
        #         '0xc0' persistent + bios
        #         '0xa0' next only  + uefi
        #         '0x80' next only  + bios
        # data2 : boot device defined in the dict _BOOTPARAM5_DATA2

        bootparam5 = '0x00 0x08 0x05 %s %s 0x00 0x00 0x00'
        if persistent:
            data1 = '0xe0' if uefi_mode else '0xc0'
        else:
            data1 = '0xa0' if uefi_mode else '0x80'
        data2 = _BOOTPARAM5_DATA2[device]

        cmd8 = bootparam5 % (data1, data2)
        ipmitool.send_raw(task, cmd8)

    @METRICS.timer('IRMCManagement.get_sensors_data')
    def get_sensors_data(self, task):
        """Get sensors data method.

        It gets sensor data from the task's node via SCCI, and convert the data
        from XML to the dict format.

        :param task: A TaskManager instance.
        :raises: FailedToGetSensorData when getting the sensor data fails.
        :raises: FailedToParseSensorData when parsing sensor data fails.
        :raises: InvalidParameterValue if required parameters are invalid.
        :raises: MissingParameterValue if a required parameter is missing.
        :returns: Returns a consistent formatted dict of sensor data grouped
                  by sensor type, which can be processed by Ceilometer.
                  Example::

                      {
                        'Sensor Type 1': {
                          'Sensor ID 1': {
                            'Sensor Reading': 'Value1 Units1',
                            'Sensor ID': 'Sensor ID 1',
                            'Units': 'Units1'
                          },
                          'Sensor ID 2': {
                            'Sensor Reading': 'Value2 Units2',
                            'Sensor ID': 'Sensor ID 2',
                            'Units': 'Units2'
                          }
                        },
                        'Sensor Type 2': {
                          'Sensor ID 3': {
                            'Sensor Reading': 'Value3 Units3',
                            'Sensor ID': 'Sensor ID 3',
                            'Units': 'Units3'
                          },
                          'Sensor ID 4': {
                            'Sensor Reading': 'Value4 Units4',
                            'Sensor ID': 'Sensor ID 4',
                            'Units': 'Units4'
                          }
                        }
                      }

        """
        # irmc_common.parse_driver_info() makes sure that
        # d_info['irmc_sensor_method'] is either 'scci' or 'ipmitool'.
        d_info = irmc_common.parse_driver_info(task.node)
        sensor_method = d_info['irmc_sensor_method']
        if sensor_method == 'scci':
            return _get_sensors_data(task)
        elif sensor_method == 'ipmitool':
            return super(IRMCManagement, self).get_sensors_data(task)

    @METRICS.timer('IRMCManagement.inject_nmi')
    @task_manager.require_exclusive_lock
    def inject_nmi(self, task):
        """Inject NMI, Non Maskable Interrupt.

        Inject NMI (Non Maskable Interrupt) for a node immediately.

        :param task: A TaskManager instance containing the node to act on.
        :raises: IRMCOperationError on an error from SCCI
        :returns: None

        """
        node = task.node
        irmc_client = irmc_common.get_irmc_client(node)
        try:
            irmc_client(irmc.scci.POWER_RAISE_NMI)
        except irmc.scci.SCCIClientError as err:
            LOG.error('iRMC Inject NMI failed for node %(node)s: %(err)s.',
                      {'node': node.uuid, 'err': err})
            raise exception.IRMCOperationError(
                operation=irmc.scci.POWER_RAISE_NMI, error=err)

    @METRICS.timer('IRMCManagement.restore_irmc_bios_config')
    @base.clean_step(
        priority=CONF.irmc.clean_priority_restore_irmc_bios_config)
    def restore_irmc_bios_config(self, task):
        """Restore BIOS config for a node.

        :param task: a task from TaskManager.
        :raises: NodeCleaningFailure, on failure to execute step.
        :returns: None.
        """
        try:
            _restore_bios_config(task)
        except exception.IRMCOperationError as e:
            raise exception.NodeCleaningFailure(node=task.node.uuid,
                                                reason=e)

    def get_secure_boot_state(self, task):
        """Get the current secure boot state for the node.

        NOTE: Not all drivers support this method. Older hardware
              may not implement that.

        :param task: A task from TaskManager.
        :raises: MissingParameterValue if a required parameter is missing
        :raises: DriverOperationError or its derivative in case
                 of driver runtime error.
        :raises: UnsupportedDriverExtension if secure boot is
                 not supported by the driver or the hardware
        :returns: Boolean
        """
        return irmc_common.get_secure_boot_mode(task.node)

    def set_secure_boot_state(self, task, state):
        """Set the current secure boot state for the node.

        NOTE: Not all drivers support this method. Older hardware
              may not implement that.

        :param task: A task from TaskManager.
        :param state: A new state as a boolean.
        :raises: MissingParameterValue if a required parameter is missing
        :raises: DriverOperationError or its derivative in case
                 of driver runtime error.
        :raises: UnsupportedDriverExtension if secure boot is
                 not supported by the driver or the hardware
        """
        return irmc_common.set_secure_boot_mode(task.node, state)
