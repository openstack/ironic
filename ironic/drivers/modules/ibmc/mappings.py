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
iBMC and Ironic constants mapping
"""

from oslo_utils import importutils

from ironic.common import boot_devices
from ironic.common import boot_modes
from ironic.common import states
from ironic.drivers.modules.ibmc import utils

constants = importutils.try_import('ibmc_client.constants')

if constants:
    # Set power state mapping
    SET_POWER_STATE_MAP = {
        states.POWER_ON: constants.RESET_ON,
        states.POWER_OFF: constants.RESET_FORCE_OFF,
        states.REBOOT: constants.RESET_FORCE_RESTART,
        states.SOFT_REBOOT: constants.RESET_FORCE_POWER_CYCLE,
        states.SOFT_POWER_OFF: constants.RESET_GRACEFUL_SHUTDOWN,
    }

    # Get power state mapping
    GET_POWER_STATE_MAP = {
        constants.SYSTEM_POWER_STATE_ON: states.POWER_ON,
        constants.SYSTEM_POWER_STATE_OFF: states.POWER_OFF,
    }

    # Boot device mapping
    GET_BOOT_DEVICE_MAP = {
        constants.BOOT_SOURCE_TARGET_NONE: 'none',
        constants.BOOT_SOURCE_TARGET_PXE: boot_devices.PXE,
        constants.BOOT_SOURCE_TARGET_FLOPPY: 'floppy',
        constants.BOOT_SOURCE_TARGET_CD: boot_devices.CDROM,
        constants.BOOT_SOURCE_TARGET_HDD: boot_devices.DISK,
        constants.BOOT_SOURCE_TARGET_BIOS_SETUP: boot_devices.BIOS,
    }

    SET_BOOT_DEVICE_MAP = utils.revert_dictionary(GET_BOOT_DEVICE_MAP)

    # Boot mode mapping
    GET_BOOT_MODE_MAP = {
        constants.BOOT_SOURCE_MODE_BIOS: boot_modes.LEGACY_BIOS,
        constants.BOOT_SOURCE_MODE_UEFI: boot_modes.UEFI,
    }

    SET_BOOT_MODE_MAP = utils.revert_dictionary(GET_BOOT_MODE_MAP)

    # Boot device persistent mapping
    GET_BOOT_DEVICE_PERSISTENT_MAP = {
        constants.BOOT_SOURCE_ENABLED_ONCE: False,
        constants.BOOT_SOURCE_ENABLED_CONTINUOUS: True,
        constants.BOOT_SOURCE_ENABLED_DISABLED: None,
    }

    SET_BOOT_DEVICE_PERSISTENT_MAP = utils.revert_dictionary(
        GET_BOOT_DEVICE_PERSISTENT_MAP)
