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

from oslo_log import log as logging
from oslo_utils import importutils

from ironic.common import boot_devices
from ironic.common import exception
from ironic.common.i18n import _, _LE
from ironic.conductor import task_manager
from ironic.drivers.modules import ipmitool
from ironic.drivers.modules.irmc import common as irmc_common
from ironic.drivers import utils as driver_utils

scci = importutils.try_import('scciclient.irmc.scci')

LOG = logging.getLogger(__name__)

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
        sensor = scci.get_sensor_data(report)

    except (exception.InvalidParameterValue,
            exception.MissingParameterValue,
            scci.SCCIInvalidInputError,
            scci.SCCIClientError) as e:
        LOG.error(_LE("SCCI get sensor data failed for node %(node_id)s "
                  "with the following error: %(error)s"),
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


class IRMCManagement(ipmitool.IPMIManagement):

    def get_properties(self):
        """Return the properties of the interface.

        :returns: Dictionary of <property name>:<property description> entries.
        """
        return irmc_common.COMMON_PROPERTIES

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
            driver_utils.get_node_capability(task.node, 'boot_mode') == 'uefi')

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
