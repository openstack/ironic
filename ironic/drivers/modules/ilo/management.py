# Copyright 2014 Hewlett-Packard Development Company, L.P.
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
iLO Management Interface
"""

from oslo.utils import importutils

from ironic.common import boot_devices
from ironic.common import exception
from ironic.common.i18n import _
from ironic.conductor import task_manager
from ironic.drivers import base
from ironic.drivers.modules.ilo import common as ilo_common
from ironic.drivers.modules import ipmitool
from ironic.openstack.common import log as logging

LOG = logging.getLogger(__name__)

ilo_client = importutils.try_import('proliantutils.ilo.ribcl')

BOOT_DEVICE_MAPPING_TO_ILO = {boot_devices.PXE: 'NETWORK',
                               boot_devices.DISK: 'HDD',
                               boot_devices.CDROM: 'CDROM'
                             }
BOOT_DEVICE_ILO_TO_GENERIC = {v: k
                              for k, v in BOOT_DEVICE_MAPPING_TO_ILO.items()}


class IloManagement(base.ManagementInterface):

    def get_properties(self):
        return ilo_common.REQUIRED_PROPERTIES

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

    def get_supported_boot_devices(self):
        """Get a list of the supported boot devices.

        :returns: A list with the supported boot devices defined
                  in :mod:`ironic.common.boot_devices`.

        """
        return list(BOOT_DEVICE_MAPPING_TO_ILO.keys())

    def get_boot_device(self, task):
        """Get the current boot device for a node.

        Returns the current boot device of the node.

        :param task: a task from TaskManager.
        :raises: MissingParameterValue if a required iLO parameter is missing.
        :raises: IloOperationError on an error from IloClient library.
        :returns: a dictionary containing:

            :boot_device:
                the boot device, one of the supported devices listed in
                :mod:`ironic.common.boot_devices` or None if it is unknown.
            :persistent:
                Whether the boot device will persist to all future boots or
                not, None if it is unknown.

        """
        ilo_object = ilo_common.get_ilo_object(task.node)
        persistent = False

        try:
            # Return one time boot device if set, else return
            # the persistent boot device
            next_boot = ilo_object.get_one_time_boot()
            if next_boot == 'Normal':
                # One time boot is not set. Check for persistent boot.
                persistent = True
                next_boot = ilo_object.get_persistent_boot_device()

        except ilo_client.IloError as ilo_exception:
            operation = _("Get boot device")
            raise exception.IloOperationError(operation=operation,
                                              error=ilo_exception)

        boot_device = BOOT_DEVICE_ILO_TO_GENERIC.get(next_boot, None)

        if boot_device is None:
            persistent = None

        return {'boot_device': boot_device, 'persistent': persistent}

    @task_manager.require_exclusive_lock
    def set_boot_device(self, task, device, persistent=False):
        """Set the boot device for a node.

        Set the boot device to use on next reboot of the node.

        :param task: a task from TaskManager.
        :param device: the boot device, one of the supported devices
                       listed in :mod:`ironic.common.boot_devices`.
        :param persistent: Boolean value. True if the boot device will
                           persist to all future boots, False if not.
                           Default: False.
        :raises: InvalidParameterValue if an invalid boot device is
                 specified.
        :raises: MissingParameterValue if a required parameter is missing.
        :raises: IloOperationError on an error from IloClient library.
        """

        try:
            boot_device = BOOT_DEVICE_MAPPING_TO_ILO[device]
        except KeyError:
            raise exception.InvalidParameterValue(_(
                "Invalid boot device %s specified.") % device)
        try:
            ilo_object = ilo_common.get_ilo_object(task.node)

            if not persistent:
                ilo_object.set_one_time_boot(boot_device)
            else:
                ilo_object.update_persistent_boot([boot_device])

        except ilo_client.IloError as ilo_exception:
            operation = _("Setting %s as boot device") % device
            raise exception.IloOperationError(operation=operation,
                                              error=ilo_exception)

        LOG.debug("Node %(uuid)s set to boot from %(device)s.",
                 {'uuid': task.node.uuid, 'device': device})

    def get_sensors_data(self, task):
        """Get sensors data.

        :param task: a TaskManager instance.
        :raises: FailedToGetSensorData when getting the sensor data fails.
        :raises: FailedToParseSensorData when parsing sensor data fails.
        :raises: InvalidParameterValue if required ipmi parameters
                 are missing.
        :raises: MissingParameterValue if a required parameter is missing.
        :returns: returns a dict of sensor data group by sensor type.

        """
        ilo_common.update_ipmi_properties(task)
        ipmi_management = ipmitool.IPMIManagement()
        return ipmi_management.get_sensors_data(task)
