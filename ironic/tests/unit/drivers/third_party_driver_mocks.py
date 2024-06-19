# Copyright 2014 Hewlett-Packard Development Company, L.P.
# All Rights Reserved.
# Copyright (c) 2021 Dell Inc. or its subsidiaries.
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
- sushy_oem_idrac
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

sushy_oem_idrac = importutils.try_import('sushy_oem_idrac')
if not sushy_oem_idrac:
    raidmode = mock.sentinel.PHYSICAL_DISK_STATE_MODE_RAID
    nonraidmode = mock.sentinel.PHYSICAL_DISK_STATE_MODE_NONRAID
    sushy_oem_idrac = mock.MagicMock(
        spec_set=mock_specs.SUSHY_OEM_IDRAC_MOD_SPEC,
        PHYSICAL_DISK_STATE_MODE_RAID=raidmode,
        PHYSICAL_DISK_STATE_MODE_NONRAID=nonraidmode,
        JOB_TYPE_RT_NO_REBOOT_CONF=mock.sentinel.JOB_TYPE_RT_NO_REBOOT_CONF,
        JOB_TYPE_RAID_CONF=mock.sentinel.JOB_TYPE_RAID_CONF
    )

    sys.modules['sushy_oem_idrac'] = sushy_oem_idrac

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


class MockKwargsException(Exception):
    def __init__(self, *args, **kwargs):
        super(MockKwargsException, self).__init__(*args)
        self.kwargs = kwargs
