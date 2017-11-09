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
- oneview_client
- pywsman
- python-dracclient
"""

import sys

import mock
from oslo_utils import importutils
import six

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
    command_exception = type('IloCommandNotSupportedError', (Exception,), {})
    proliantutils.exception.IloCommandNotSupportedError = command_exception
    proliantutils.exception.InvalidInputError = type(
        'InvalidInputError', (Exception,), {})
    proliantutils.exception.ImageExtractionFailed = type(
        'ImageExtractionFailed', (Exception,), {})
    if 'ironic.drivers.ilo' in sys.modules:
        six.moves.reload_module(sys.modules['ironic.drivers.ilo'])


oneview_client = importutils.try_import('oneview_client')
if not oneview_client:
    oneview_client = mock.MagicMock(spec_set=mock_specs.ONEVIEWCLIENT_SPEC)
    sys.modules['oneview_client'] = oneview_client
    sys.modules['oneview_client.client'] = oneview_client.client
    states = mock.MagicMock(
        spec_set=mock_specs.ONEVIEWCLIENT_STATES_SPEC,
        ONEVIEW_POWER_OFF='Off',
        ONEVIEW_POWERING_OFF='PoweringOff',
        ONEVIEW_POWER_ON='On',
        ONEVIEW_POWERING_ON='PoweringOn',
        ONEVIEW_RESETTING='Resetting',
        ONEVIEW_ERROR='error')
    sys.modules['oneview_client.states'] = states
    sys.modules['oneview_client.exceptions'] = oneview_client.exceptions
    sys.modules['oneview_client.utils'] = oneview_client.utils
    oneview_client.exceptions.OneViewException = type('OneViewException',
                                                      (Exception,), {})
    sys.modules['oneview_client.models'] = oneview_client.models

oneview_client_module = importutils.try_import('oneview_client.client')
# NOTE(vdrok): Always mock the oneview client, as it tries to establish
# connection to oneview right in __init__, and stevedore does not seem to care
# about mocks when it loads a module in mock_the_extension_manager
sys.modules['oneview_client.client'].Client = mock.MagicMock(
    spec_set=mock_specs.ONEVIEWCLIENT_CLIENT_CLS_SPEC
)
if 'ironic.drivers.oneview' in sys.modules:
    six.moves.reload_module(sys.modules['ironic.drivers.modules.oneview'])


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
    sys.modules['dracclient'] = dracclient
    sys.modules['dracclient.client'] = dracclient.client
    sys.modules['dracclient.constants'] = dracclient.constants
    sys.modules['dracclient.exceptions'] = dracclient.exceptions
    dracclient.exceptions.BaseClientException = type('BaseClientException',
                                                     (Exception,), {})
    # Now that the external library has been mocked, if anything had already
    # loaded any of the drivers, reload them.
    if 'ironic.drivers.modules.drac' in sys.modules:
        six.moves.reload_module(sys.modules['ironic.drivers.modules.drac'])

# attempt to load the external 'pysnmp' library, which is required by
# the optional drivers.modules.snmp module
pysnmp = importutils.try_import("pysnmp")
if not pysnmp:
    pysnmp = mock.MagicMock(spec_set=mock_specs.PYWSNMP_SPEC)
    sys.modules["pysnmp"] = pysnmp
    sys.modules["pysnmp.entity"] = pysnmp.entity
    sys.modules["pysnmp.entity.rfc3413"] = pysnmp.entity.rfc3413
    sys.modules["pysnmp.entity.rfc3413.oneliner"] = (
        pysnmp.entity.rfc3413.oneliner)
    sys.modules["pysnmp.entity.rfc3413.oneliner.cmdgen"] = (
        pysnmp.entity.rfc3413.oneliner.cmdgen)
    sys.modules["pysnmp.error"] = pysnmp.error
    pysnmp.error.PySnmpError = Exception
    sys.modules["pysnmp.proto"] = pysnmp.proto
    sys.modules["pysnmp.proto.rfc1902"] = pysnmp.proto.rfc1902
    # Patch the RFC1902 integer class with a python int
    pysnmp.proto.rfc1902.Integer = int


# if anything has loaded the snmp driver yet, reload it now that the
# external library has been mocked
if 'ironic.drivers.modules.snmp' in sys.modules:
    six.moves.reload_module(sys.modules['ironic.drivers.modules.snmp'])


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
    six.moves.reload_module(sys.modules['ironic.drivers.modules.irmc'])


# install mock object to prevent 'iscsi_irmc' and 'agent_irmc' from
# checking whether NFS/CIFS share file system is mounted or not.
irmc_boot = importutils.import_module(
    'ironic.drivers.modules.irmc.boot')
irmc_boot.check_share_fs_mounted_orig = irmc_boot.check_share_fs_mounted
irmc_boot.check_share_fs_mounted_patcher = mock.patch(
    'ironic.drivers.modules.irmc.boot.check_share_fs_mounted')
irmc_boot.check_share_fs_mounted_patcher.return_value = None


ironic_inspector_client = importutils.try_import('ironic_inspector_client')
if not ironic_inspector_client:
    ironic_inspector_client = mock.MagicMock(
        spec_set=mock_specs.IRONIC_INSPECTOR_CLIENT_SPEC)
    ironic_inspector_client.ClientV1 = mock_specs.InspectorClientV1Specs
    sys.modules['ironic_inspector_client'] = ironic_inspector_client
    if 'ironic.drivers.modules.inspector' in sys.modules:
        six.moves.reload_module(
            sys.modules['ironic.drivers.modules.inspector'])


class MockKwargsException(Exception):
    def __init__(self, *args, **kwargs):
        super(MockKwargsException, self).__init__(*args)
        self.kwargs = kwargs


ucssdk = importutils.try_import('UcsSdk')
if not ucssdk:
    ucssdk = mock.MagicMock()
    sys.modules['UcsSdk'] = ucssdk
    sys.modules['UcsSdk.utils'] = ucssdk.utils
    sys.modules['UcsSdk.utils.power'] = ucssdk.utils.power
    sys.modules['UcsSdk.utils.management'] = ucssdk.utils.management
    sys.modules['UcsSdk.utils.exception'] = ucssdk.utils.exception
    ucssdk.utils.exception.UcsOperationError = (
        type('UcsOperationError', (MockKwargsException,), {}))
    ucssdk.utils.exception.UcsConnectionError = (
        type('UcsConnectionError', (MockKwargsException,), {}))
    if 'ironic.drivers.modules.ucs' in sys.modules:
        six.moves.reload_module(
            sys.modules['ironic.drivers.modules.ucs'])

imcsdk = importutils.try_import('ImcSdk')
if not imcsdk:
    imcsdk = mock.MagicMock()
    imcsdk.ImcException = Exception
    sys.modules['ImcSdk'] = imcsdk
    if 'ironic.drivers.modules.cimc' in sys.modules:
        six.moves.reload_module(
            sys.modules['ironic.drivers.modules.cimc'])


sushy = importutils.try_import('sushy')
if not sushy:
    sushy = mock.MagicMock(
        spec_set=mock_specs.SUSHY_CONSTANTS_SPEC,
        BOOT_SOURCE_TARGET_PXE='Pxe',
        BOOT_SOURCE_TARGET_HDD='Hdd',
        BOOT_SOURCE_TARGET_CD='Cd',
        BOOT_SOURCE_TARGET_BIOS_SETUP='BiosSetup',
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
        BOOT_SOURCE_ENABLED_ONCE='once'
    )

    sys.modules['sushy'] = sushy
    if 'ironic.drivers.modules.redfish' in sys.modules:
        six.moves.reload_module(
            sys.modules['ironic.drivers.modules.redfish'])
