# Copyright 2019 HUAWEI, Inc. All Rights Reserved.
# Copyright 2017 Red Hat, Inc. All Rights Reserved.
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
iBMC Management Interface
"""

from oslo_log import log
from oslo_utils import importutils

from ironic.common import exception
from ironic.common.i18n import _
from ironic.conductor import task_manager
from ironic.drivers import base
from ironic.drivers.modules.ibmc import mappings
from ironic.drivers.modules.ibmc import utils

constants = importutils.try_import('ibmc_client.constants')
ibmc_client = importutils.try_import('ibmc_client')

LOG = log.getLogger(__name__)


class IBMCManagement(base.ManagementInterface):

    # NOTE(TheJulia): Deprecating November 2023 in favor of Redfish
    # and due to a lack of active driver maintenance.
    supported = False

    def __init__(self):
        """Initialize the iBMC management interface

        :raises: DriverLoadError if the driver can't be loaded due to
            missing dependencies
        """
        super(IBMCManagement, self).__init__()
        if not ibmc_client:
            raise exception.DriverLoadError(
                driver='ibmc',
                reason=_('Unable to import the python-ibmcclient library'))

    def get_properties(self):
        """Return the properties of the interface.

        :returns: dictionary of <property name>:<property description> entries.
        """
        return utils.COMMON_PROPERTIES.copy()

    def validate(self, task):
        """Validates the driver information needed by the iBMC driver.

        :param task: A TaskManager instance containing the node to act on.
        :raises: InvalidParameterValue on malformed parameter(s)
        :raises: MissingParameterValue on missing parameter(s)
        """
        utils.parse_driver_info(task.node)

    @utils.handle_ibmc_exception('get iBMC supported boot devices')
    def get_supported_boot_devices(self, task):
        """Get a list of the supported boot devices.

        :param task: a task from TaskManager.
        :raises: InvalidParameterValue on malformed parameter(s)
        :raises: MissingParameterValue on missing parameter(s)
        :raises: IBMCConnectionError when it fails to connect to iBMC
        :raises: IBMCError when iBMC responses an error information
        :returns: A list with the supported boot devices defined
                  in :mod:`ironic.common.boot_devices`.
        """
        ibmc = utils.parse_driver_info(task.node)
        with ibmc_client.connect(**ibmc) as conn:
            system = conn.system.get()
            boot_source_override = system.boot_source_override
            return list(map(mappings.GET_BOOT_DEVICE_MAP.get,
                            boot_source_override.supported_boot_devices))

    @task_manager.require_exclusive_lock
    @utils.handle_ibmc_exception('set iBMC boot device')
    def set_boot_device(self, task, device, persistent=False):
        """Set the boot device for a node.

        :param task: A task from TaskManager.
        :param device: The boot device, one of
                       :mod:`ironic.common.boot_device`.
        :param persistent: Boolean value. True if the boot device will
                           persist to all future boots, False if not.
                           Default: False.
        :raises: InvalidParameterValue on malformed parameter(s)
        :raises: MissingParameterValue on missing parameter(s)
        :raises: IBMCConnectionError when it fails to connect to iBMC
        :raises: IBMCError when iBMC responses an error information
        """
        ibmc = utils.parse_driver_info(task.node)
        with ibmc_client.connect(**ibmc) as conn:
            boot_device = mappings.SET_BOOT_DEVICE_MAP[device]
            enabled = mappings.SET_BOOT_DEVICE_PERSISTENT_MAP[persistent]
            conn.system.set_boot_source(boot_device, enabled=enabled)

    @utils.handle_ibmc_exception('get iBMC boot device')
    def get_boot_device(self, task):
        """Get the current boot device for a node.

        :param task: A task from TaskManager.
        :raises: InvalidParameterValue on malformed parameter(s)
        :raises: MissingParameterValue on missing parameter(s)
        :raises: IBMCConnectionError when it fails to connect to iBMC
        :raises: IBMCError when iBMC responses an error information
        :returns: a dictionary containing:

            :boot_device:
                the boot device, one of :mod:`ironic.common.boot_devices` or
                None if it is unknown.
            :persistent:
                Boolean value or None, True if the boot device persists,
                False otherwise. None if it's disabled.

        """
        ibmc = utils.parse_driver_info(task.node)
        with ibmc_client.connect(**ibmc) as conn:
            system = conn.system.get()
            boot_source_override = system.boot_source_override
            boot_device = boot_source_override.target
            enabled = boot_source_override.enabled
            return {
                'boot_device': mappings.GET_BOOT_DEVICE_MAP.get(boot_device),
                'persistent':
                    mappings.GET_BOOT_DEVICE_PERSISTENT_MAP.get(enabled)
            }

    def get_supported_boot_modes(self, task):
        """Get a list of the supported boot modes.

        :param task: A task from TaskManager.
        :returns: A list with the supported boot modes defined
                  in :mod:`ironic.common.boot_modes`. If boot
                  mode support can't be determined, empty list
                  is returned.
        """
        return list(mappings.SET_BOOT_MODE_MAP)

    @task_manager.require_exclusive_lock
    @utils.handle_ibmc_exception('set iBMC boot mode')
    def set_boot_mode(self, task, mode):
        """Set the boot mode for a node.

        Set the boot mode to use on next reboot of the node.

        :param task: A task from TaskManager.
        :param mode: The boot mode, one of
                     :mod:`ironic.common.boot_modes`.
        :raises: InvalidParameterValue on malformed parameter(s)
        :raises: MissingParameterValue on missing parameter(s)
        :raises: IBMCConnectionError when it fails to connect to iBMC
        :raises: IBMCError when iBMC responses an error information
        """
        ibmc = utils.parse_driver_info(task.node)
        with ibmc_client.connect(**ibmc) as conn:
            system = conn.system.get()
            boot_source_override = system.boot_source_override
            boot_device = boot_source_override.target
            boot_override = boot_source_override.enabled

            # Copied from redfish driver
            # TODO(Qianbiao.NG) what if boot device is "NONE"?
            if not boot_device:
                error_msg = (_('Cannot change boot mode on node %(node)s '
                               'because its boot device is not set.') %
                             {'node': task.node.uuid})
                LOG.error(error_msg)
                raise exception.IBMCError(error_msg)

            # TODO(Qianbiao.NG) what if boot override is "disabled"?
            if not boot_override:
                i18n = _('Cannot change boot mode on node %(node)s '
                         'because its boot source override is not set.')
                error_msg = i18n % {'node': task.node.uuid}
                LOG.error(error_msg)
                raise exception.IBMCError(error_msg)

            boot_mode = mappings.SET_BOOT_MODE_MAP[mode]
            conn.system.set_boot_source(boot_device,
                                        enabled=boot_override,
                                        mode=boot_mode)

    @utils.handle_ibmc_exception('get iBMC boot mode')
    def get_boot_mode(self, task):
        """Get the current boot mode for a node.

        Provides the current boot mode of the node.

        :param task: A task from TaskManager.
        :raises: InvalidParameterValue on malformed parameter(s)
        :raises: MissingParameterValue on missing parameter(s)
        :raises: IBMCConnectionError when it fails to connect to iBMC
        :raises: IBMCError when iBMC responses an error information
        :returns: The boot mode, one of :mod:`ironic.common.boot_mode` or
                  None if it is unknown.
        """
        ibmc = utils.parse_driver_info(task.node)
        with ibmc_client.connect(**ibmc) as conn:
            system = conn.system.get()
            boot_source_override = system.boot_source_override
            boot_mode = boot_source_override.mode
            return mappings.GET_BOOT_MODE_MAP.get(boot_mode)

    def get_sensors_data(self, task):
        """Get sensors data.

        Not implemented for this driver.

        :raises: NotImplementedError
        """
        raise NotImplementedError()

    @task_manager.require_exclusive_lock
    @utils.handle_ibmc_exception('inject iBMC NMI')
    def inject_nmi(self, task):
        """Inject NMI, Non Maskable Interrupt.

        Inject NMI (Non Maskable Interrupt) for a node immediately.

        :param task: A TaskManager instance containing the node to act on.
        :raises: InvalidParameterValue on malformed parameter(s)
        :raises: MissingParameterValue on missing parameter(s)
        :raises: IBMCConnectionError when it fails to connect to iBMC
        :raises: IBMCError when iBMC responses an error information
        """
        ibmc = utils.parse_driver_info(task.node)
        with ibmc_client.connect(**ibmc) as conn:
            conn.system.reset(constants.RESET_NMI)
