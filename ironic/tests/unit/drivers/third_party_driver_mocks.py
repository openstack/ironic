# Copyright 2014 Hewlett-Packard Development Company, L.P.
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

"""This module detects whether third-party libraries, utilized by third-party
drivers, are present on the system. If they are not, it mocks them and tinkers
with sys.modules so that the drivers can be loaded by unit tests, and the unit
tests can continue to test the functionality of those drivers without the
respective external libraries' actually being present.

Any external library required by a third-party driver should be mocked here.
Current list of mocked libraries:

- proliantutils
- pysnmp
- scciclient
- python-dracclient
- python-ibmcclient
"""

import importlib
import sys
from unittest import mock

from oslo_utils import importutils

from ironic.drivers.modules import ipmitool
from ironic.tests.unit.drivers import third_party_driver_mock_specs \
    as mock_specs


# IPMITool driver checks the system for presence of 'ipmitool' binary during
# __init__. We bypass that check in order to run the unit tests, which do not
# depend on 'ipmitool' being on the system.
ipmitool.TIMING_SUPPORT = False
ipmitool.DUAL_BRIDGE_SUPPORT = False
ipmitool.SINGLE_BRIDGE_SUPPORT = False

proliantutils = importutils.try_import('proliantutils')
if not proliantutils:
    proliantutils = mock.MagicMock(spec_set=mock_specs.PROLIANTUTILS_SPEC)
    sys.modules['proliantutils'] = proliantutils
    sys.modules['proliantutils.ilo'] = proliantutils.ilo
    sys.modules['proliantutils.ilo.client'] = proliantutils.ilo.client
    sys.modules['proliantutils.exception'] = proliantutils.exception
    sys.modules['proliantutils.utils'] = proliantutils.utils
    proliantutils.utils.process_firmware_image = mock.MagicMock()
    proliantutils.exception.IloError = type('IloError', (Exception,), {})
    proliantutils.exception.IloLogicalDriveNotFoundError = (
        type('IloLogicalDriveNotFoundError', (Exception,), {}))
    command_exception = type('IloCommandNotSupportedError', (Exception,), {})
    proliantutils.exception.IloCommandNotSupportedError = command_exception
    proliantutils.exception.IloCommandNotSupportedInBiosError = type(
        'IloCommandNotSupportedInBiosError', (Exception,), {})
    proliantutils.exception.InvalidInputError = type(
        'InvalidInputError', (Exception,), {})
    proliantutils.exception.ImageExtractionFailed = type(
        'ImageExtractionFailed', (Exception,), {})
    if 'ironic.drivers.ilo' in sys.modules:
        importlib.reload(sys.modules['ironic.drivers.ilo'])

redfish = importutils.try_import('redfish')
if not redfish:
    redfish = mock.MagicMock(spec_set=mock_specs.REDFISH_SPEC)
    sys.modules['redfish'] = redfish

if 'ironic.drivers.redfish' in sys.modules:
    importlib.reload(sys.modules['ironic.drivers.modules.redfish'])

# attempt to load the external 'python-dracclient' library, which is required
# by the optional drivers.modules.drac module
dracclient = importutils.try_import('dracclient')
if not dracclient:
    dracclient = mock.MagicMock(spec_set=mock_specs.DRACCLIENT_SPEC)
    dracclient.client = mock.MagicMock(
        spec_set=mock_specs.DRACCLIENT_CLIENT_MOD_SPEC)
    dracclient.constants = mock.MagicMock(
        spec_set=mock_specs.DRACCLIENT_CONSTANTS_MOD_SPEC,
        POWER_OFF=mock.sentinel.POWER_OFF,
        POWER_ON=mock.sentinel.POWER_ON,
        REBOOT=mock.sentinel.REBOOT)
    dracclient.constants.RebootRequired = mock.MagicMock(
        spec_set=mock_specs.DRACCLIENT_CONSTANTS_REBOOT_REQUIRED_MOD_SPEC,
        true=mock.sentinel.true,
        optional=mock.sentinel.optional,
        false=mock.sentinel.false)
    dracclient.constants.RaidStatus = mock.MagicMock(
        spec_set=mock_specs.DRACCLIENT_CONSTANTS_RAID_STATUS_MOD_SPEC,
        jbod=mock.sentinel.jbod,
        raid=mock.sentinel.raid)

    sys.modules['dracclient'] = dracclient
    sys.modules['dracclient.client'] = dracclient.client
    sys.modules['dracclient.constants'] = dracclient.constants
    sys.modules['dracclient.exceptions'] = dracclient.exceptions
    dracclient.exceptions.BaseClientException = type('BaseClientException',
                                                     (Exception,), {})

    dracclient.exceptions.DRACRequestFailed = type(
        'DRACRequestFailed', (dracclient.exceptions.BaseClientException,), {})

    class DRACOperationFailed(dracclient.exceptions.DRACRequestFailed):
        def __init__(self, **kwargs):
            super(DRACOperationFailed, self).__init__(
                'DRAC operation failed. Messages: %(drac_messages)s' % kwargs)

    dracclient.exceptions.DRACOperationFailed = DRACOperationFailed

    # Now that the external library has been mocked, if anything had already
    # loaded any of the drivers, reload them.
    if 'ironic.drivers.modules.drac' in sys.modules:
        importlib.reload(sys.modules['ironic.drivers.modules.drac'])


# attempt to load the external 'pysnmp' library, which is required by
# the optional drivers.modules.snmp module
pysnmp = importutils.try_import("pysnmp")
if not pysnmp:
    pysnmp = mock.MagicMock(spec_set=mock_specs.PYWSNMP_SPEC)
    sys.modules["pysnmp"] = pysnmp
    sys.modules["pysnmp.hlapi"] = pysnmp.hlapi
    sys.modules["pysnmp.error"] = pysnmp.error
    pysnmp.error.PySnmpError = Exception
    # Patch the RFC1902 integer class with a python int
    pysnmp.hlapi.Integer = int


# if anything has loaded the snmp driver yet, reload it now that the
# external library has been mocked
if 'ironic.drivers.modules.snmp' in sys.modules:
    importlib.reload(sys.modules['ironic.drivers.modules.snmp'])


# attempt to load the external 'scciclient' library, which is required by
# the optional drivers.modules.irmc module
scciclient = importutils.try_import('scciclient')
if not scciclient:
    mock_scciclient = mock.MagicMock(spec_set=mock_specs.SCCICLIENT_SPEC)
    sys.modules['scciclient'] = mock_scciclient
    sys.modules['scciclient.irmc'] = mock_scciclient.irmc
    sys.modules['scciclient.irmc.scci'] = mock.MagicMock(
        spec_set=mock_specs.SCCICLIENT_IRMC_SCCI_SPEC,
        POWER_OFF=mock.sentinel.POWER_OFF,
        POWER_ON=mock.sentinel.POWER_ON,
        POWER_RESET=mock.sentinel.POWER_RESET,
        MOUNT_CD=mock.sentinel.MOUNT_CD,
        UNMOUNT_CD=mock.sentinel.UNMOUNT_CD,
        MOUNT_FD=mock.sentinel.MOUNT_FD,
        UNMOUNT_FD=mock.sentinel.UNMOUNT_FD)
    sys.modules['scciclient.irmc.elcm'] = mock.MagicMock(
        spec_set=mock_specs.SCCICLIENT_IRMC_ELCM_SPEC)


# if anything has loaded the iRMC driver yet, reload it now that the
# external library has been mocked
if 'ironic.drivers.modules.irmc' in sys.modules:
    importlib.reload(sys.modules['ironic.drivers.modules.irmc'])


# install mock object to prevent the irmc-virtual-media boot interface from
# checking whether NFS/CIFS share file system is mounted or not.
irmc_boot = importutils.import_module(
    'ironic.drivers.modules.irmc.boot')
irmc_boot.check_share_fs_mounted_orig = irmc_boot.check_share_fs_mounted
irmc_boot.check_share_fs_mounted_patcher = mock.patch(
    'ironic.drivers.modules.irmc.boot.check_share_fs_mounted')
irmc_boot.check_share_fs_mounted_patcher.return_value = None


class MockKwargsException(Exception):
    def __init__(self, *args, **kwargs):
        super(MockKwargsException, self).__init__(*args)
        self.kwargs = kwargs


sushy = importutils.try_import('sushy')
if not sushy:
    sushy = mock.MagicMock(
        spec_set=mock_specs.SUSHY_SPEC,
        BOOT_SOURCE_TARGET_PXE='Pxe',
        BOOT_SOURCE_TARGET_HDD='Hdd',
        BOOT_SOURCE_TARGET_CD='Cd',
        BOOT_SOURCE_TARGET_BIOS_SETUP='BiosSetup',
        INDICATOR_LED_LIT='indicator led lit',
        INDICATOR_LED_BLINKING='indicator led blinking',
        INDICATOR_LED_OFF='indicator led off',
        INDICATOR_LED_UNKNOWN='indicator led unknown',
        SYSTEM_POWER_STATE_ON='on',
        SYSTEM_POWER_STATE_POWERING_ON='powering on',
        SYSTEM_POWER_STATE_OFF='off',
        SYSTEM_POWER_STATE_POWERING_OFF='powering off',
        RESET_ON='on',
        RESET_FORCE_OFF='force off',
        RESET_GRACEFUL_SHUTDOWN='graceful shutdown',
        RESET_GRACEFUL_RESTART='graceful restart',
        RESET_FORCE_RESTART='force restart',
        RESET_NMI='nmi',
        BOOT_SOURCE_ENABLED_CONTINUOUS='continuous',
        BOOT_SOURCE_ENABLED_ONCE='once',
        BOOT_SOURCE_MODE_BIOS='bios',
        BOOT_SOURCE_MODE_UEFI='uefi',
        PROCESSOR_ARCH_x86='x86 or x86-64',
        PROCESSOR_ARCH_IA_64='Intel Itanium',
        PROCESSOR_ARCH_ARM='ARM',
        PROCESSOR_ARCH_MIPS='MIPS',
        PROCESSOR_ARCH_OEM='OEM-defined',
        STATE_ENABLED='enabled',
        STATE_DISABLED='disabled',
        STATE_ABSENT='absent',
        VIRTUAL_MEDIA_CD='cd',
        VIRTUAL_MEDIA_FLOPPY='floppy',
    )

    sys.modules['sushy'] = sushy
    sys.modules['sushy.exceptions'] = sushy.exceptions
    sushy.exceptions.SushyError = (
        type('SushyError', (MockKwargsException,), {}))
    sushy.exceptions.ConnectionError = (
        type('ConnectionError', (sushy.exceptions.SushyError,), {}))
    sushy.exceptions.ResourceNotFoundError = (
        type('ResourceNotFoundError', (sushy.exceptions.SushyError,), {}))
    sushy.exceptions.MissingAttributeError = (
        type('MissingAttributeError', (sushy.exceptions.SushyError,), {}))
    sushy.exceptions.OEMExtensionNotFoundError = (
        type('OEMExtensionNotFoundError', (sushy.exceptions.SushyError,), {}))
    sushy.auth = mock.MagicMock(spec_set=mock_specs.SUSHY_AUTH_SPEC)
    sys.modules['sushy.auth'] = sushy.auth

    if 'ironic.drivers.modules.redfish' in sys.modules:
        importlib.reload(sys.modules['ironic.drivers.modules.redfish'])

xclarity_client = importutils.try_import('xclarity_client')
if not xclarity_client:
    xclarity_client = mock.MagicMock(spec_set=mock_specs.XCLARITY_SPEC)
    sys.modules['xclarity_client'] = xclarity_client
    sys.modules['xclarity_client.client'] = xclarity_client.client
    states = mock.MagicMock(
        spec_set=mock_specs.XCLARITY_STATES_SPEC,
        STATE_POWER_ON="power on",
        STATE_POWER_OFF="power off",
        STATE_POWERING_ON="powering_on",
        STATE_POWERING_OFF="powering_off")
    sys.modules['xclarity_client.states'] = states
    sys.modules['xclarity_client.exceptions'] = xclarity_client.exceptions
    sys.modules['xclarity_client.utils'] = xclarity_client.utils
    xclarity_client.exceptions.XClarityException = type('XClarityException',
                                                        (Exception,), {})
    sys.modules['xclarity_client.models'] = xclarity_client.models


# python-ibmcclient mocks for HUAWEI rack server driver
ibmc_client = importutils.try_import('ibmc_client')
if not ibmc_client:
    ibmc_client = mock.MagicMock(spec_set=mock_specs.IBMCCLIENT_SPEC)
    sys.modules['ibmc_client'] = ibmc_client

    # Mock iBMC client exceptions
    exceptions = mock.MagicMock()
    exceptions.ConnectionError = (
        type('ConnectionError', (MockKwargsException,), {}))
    exceptions.IBMCClientError = (
        type('IBMCClientError', (MockKwargsException,), {}))
    sys.modules['ibmc_client.exceptions'] = exceptions

    # Mock iIBMC client constants
    constants = mock.MagicMock(
        SYSTEM_POWER_STATE_ON='On',
        SYSTEM_POWER_STATE_OFF='Off',
        BOOT_SOURCE_TARGET_NONE='None',
        BOOT_SOURCE_TARGET_PXE='Pxe',
        BOOT_SOURCE_TARGET_FLOPPY='Floppy',
        BOOT_SOURCE_TARGET_CD='Cd',
        BOOT_SOURCE_TARGET_HDD='Hdd',
        BOOT_SOURCE_TARGET_BIOS_SETUP='BiosSetup',
        BOOT_SOURCE_MODE_BIOS='Legacy',
        BOOT_SOURCE_MODE_UEFI='UEFI',
        BOOT_SOURCE_ENABLED_ONCE='Once',
        BOOT_SOURCE_ENABLED_CONTINUOUS='Continuous',
        BOOT_SOURCE_ENABLED_DISABLED='Disabled',
        RESET_NMI='Nmi',
        RESET_ON='On',
        RESET_FORCE_OFF='ForceOff',
        RESET_GRACEFUL_SHUTDOWN='GracefulShutdown',
        RESET_FORCE_RESTART='ForceRestart',
        RESET_FORCE_POWER_CYCLE='ForcePowerCycle')
    sys.modules['ibmc_client.constants'] = constants

    if 'ironic.drivers.modules.ibmc' in sys.modules:
        importlib.reload(sys.modules['ironic.drivers.modules.ibmc'])
