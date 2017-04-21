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

from oslo_log import log
from oslo_utils import importutils

from ironic.common import boot_devices
from ironic.common import exception
from ironic.common.i18n import _
from ironic.conductor import task_manager
from ironic.drivers import base
from ironic.drivers.modules.redfish import utils as redfish_utils

LOG = log.getLogger(__name__)

sushy = importutils.try_import('sushy')

if sushy:
    BOOT_DEVICE_MAP = {
        sushy.BOOT_SOURCE_TARGET_PXE: boot_devices.PXE,
        sushy.BOOT_SOURCE_TARGET_HDD: boot_devices.DISK,
        sushy.BOOT_SOURCE_TARGET_CD: boot_devices.CDROM,
        sushy.BOOT_SOURCE_TARGET_BIOS_SETUP: boot_devices.BIOS
    }

    BOOT_DEVICE_MAP_REV = {v: k for k, v in BOOT_DEVICE_MAP.items()}

    BOOT_DEVICE_PERSISTENT_MAP = {
        sushy.BOOT_SOURCE_ENABLED_CONTINUOUS: True,
        sushy.BOOT_SOURCE_ENABLED_ONCE: False
    }

    BOOT_DEVICE_PERSISTENT_MAP_REV = {v: k for k, v in
                                      BOOT_DEVICE_PERSISTENT_MAP.items()}


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
        system = redfish_utils.get_system(task.node)
        # TODO(lucasagomes): set_system_boot_source() also supports mode
        # for UEFI and BIOS we should get it from instance_info and pass
        # it along this call
        try:
            system.set_system_boot_source(
                BOOT_DEVICE_MAP_REV[device],
                enabled=BOOT_DEVICE_PERSISTENT_MAP_REV[persistent])
        except sushy.exceptions.SushyError as e:
            error_msg = (_('Redfish set boot device failed for node '
                           '%(node)s. Error: %(error)s') %
                         {'node': task.node.uuid, 'error': e})
            LOG.error(error_msg)
            raise exception.RedfishError(error=error_msg)

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

    def get_sensors_data(self, task):
        """Get sensors data.

        Not implemented for this driver.

        :raises: NotImplementedError
        """
        raise NotImplementedError()

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
