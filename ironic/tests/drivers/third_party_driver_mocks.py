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

- seamicroclient
- ipminative
- proliantutils
- pysnmp
- scciclient
"""

import sys

import mock
from oslo_utils import importutils

from ironic.drivers.modules import ipmitool


# attempt to load the external 'seamicroclient' library, which is
# required by the optional drivers.modules.seamicro module
seamicroclient = importutils.try_import("seamicroclient")
if not seamicroclient:
    smc = mock.Mock()
    smc.client = mock.Mock()
    smc.exceptions = mock.Mock()
    smc.exceptions.ClientException = Exception
    smc.exceptions.UnsupportedVersion = Exception
    sys.modules['seamicroclient'] = smc
    sys.modules['seamicroclient.client'] = smc.client
    sys.modules['seamicroclient.exceptions'] = smc.exceptions

# if anything has loaded the seamicro driver yet, reload it now that
# the external library has been mocked
if 'ironic.drivers.modules.seamicro' in sys.modules:
    reload(sys.modules['ironic.drivers.modules.seamicro'])

# IPMITool driver checks the system for presence of 'ipmitool' binary during
# __init__. We bypass that check in order to run the unit tests, which do not
# depend on 'ipmitool' being on the system.
ipmitool.TIMING_SUPPORT = False
ipmitool.DUAL_BRIDGE_SUPPORT = False
ipmitool.SINGLE_BRIDGE_SUPPORT = False

pyghmi = importutils.try_import("pyghmi")
if not pyghmi:
    p = mock.Mock()
    p.exceptions = mock.Mock()
    p.exceptions.IpmiException = Exception
    p.ipmi = mock.Mock()
    p.ipmi.command = mock.Mock()
    p.ipmi.command.Command = mock.Mock()
    sys.modules['pyghmi'] = p
    sys.modules['pyghmi.exceptions'] = p.exceptions
    sys.modules['pyghmi.ipmi'] = p.ipmi
    sys.modules['pyghmi.ipmi.command'] = p.ipmi.command
    # FIXME(deva): the next line is a hack, because several unit tests
    #              actually depend on this particular string being present
    #              in pyghmi.ipmi.command.boot_devices
    p.ipmi.command.boot_devices = {'pxe': 4}

if 'ironic.drivers.modules.ipminative' in sys.modules:
    reload(sys.modules['ironic.drivers.modules.ipminative'])

proliantutils = importutils.try_import('proliantutils')
if not proliantutils:
    proliantutils = mock.MagicMock()
    sys.modules['proliantutils'] = proliantutils
    sys.modules['proliantutils.ilo'] = proliantutils.ilo
    sys.modules['proliantutils.ilo.client'] = proliantutils.ilo.client
    sys.modules['proliantutils.exception'] = proliantutils.exception
    proliantutils.exception.IloError = type('IloError', (Exception,), {})
    command_exception = type('IloCommandNotSupportedError', (Exception,), {})
    proliantutils.exception.IloCommandNotSupportedError = command_exception
    if 'ironic.drivers.ilo' in sys.modules:
        reload(sys.modules['ironic.drivers.ilo'])


# attempt to load the external 'pywsman' library, which is required by
# the optional drivers.modules.drac and drivers.modules.amt module
pywsman = importutils.try_import('pywsman')
if not pywsman:
    pywsman = mock.Mock()
    sys.modules['pywsman'] = pywsman
    # Now that the external library has been mocked, if anything had already
    # loaded any of the drivers, reload them.
    if 'ironic.drivers.modules.drac' in sys.modules:
        reload(sys.modules['ironic.drivers.modules.drac'])
    if 'ironic.drivers.modules.amt' in sys.modules:
        reload(sys.modules['ironic.drivers.modules.amt'])


# attempt to load the external 'iboot' library, which is required by
# the optional drivers.modules.iboot module
iboot = importutils.try_import("iboot")
if not iboot:
    ib = mock.Mock()
    ib.iBootInterface = mock.Mock()
    sys.modules['iboot'] = ib

# if anything has loaded the iboot driver yet, reload it now that the
# external library has been mocked
if 'ironic.drivers.modules.iboot' in sys.modules:
    reload(sys.modules['ironic.drivers.modules.iboot'])


# attempt to load the external 'pysnmp' library, which is required by
# the optional drivers.modules.snmp module
pysnmp = importutils.try_import("pysnmp")
if not pysnmp:
    pysnmp = mock.Mock()
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
    reload(sys.modules['ironic.drivers.modules.snmp'])


# attempt to load the external 'scciclient' library, which is required by
# the optional drivers.modules.irmc module
scciclient = importutils.try_import('scciclient')
if not scciclient:
    mock_scciclient = mock.MagicMock()
    sys.modules['scciclient'] = mock_scciclient
    sys.modules['scciclient.irmc'] = mock_scciclient.irmc
    sys.modules['scciclient.irmc.scci'] = mock.MagicMock(
        POWER_OFF=mock.sentinel.POWER_OFF,
        POWER_ON=mock.sentinel.POWER_ON,
        POWER_RESET=mock.sentinel.POWER_RESET)


# if anything has loaded the iRMC driver yet, reload it now that the
# external library has been mocked
if 'ironic.drivers.modules.irmc' in sys.modules:
    reload(sys.modules['ironic.drivers.modules.irmc'])

pyremotevbox = importutils.try_import('pyremotevbox')
if not pyremotevbox:
    pyremotevbox = mock.MagicMock()
    pyremotevbox.exception = mock.MagicMock()
    pyremotevbox.exception.PyRemoteVBoxException = Exception
    pyremotevbox.exception.VmInWrongPowerState = Exception
    sys.modules['pyremotevbox'] = pyremotevbox
    if 'ironic.drivers.modules.virtualbox' in sys.modules:
        reload(sys.modules['ironic.drivers.modules.virtualbox'])


ironic_discoverd = importutils.try_import('ironic_discoverd')
if not ironic_discoverd:
    ironic_discoverd = mock.MagicMock()
    ironic_discoverd.__version_info__ = (1, 0, 0)
    ironic_discoverd.__version__ = "1.0.0"
    sys.modules['ironic_discoverd'] = ironic_discoverd
    sys.modules['ironic_discoverd.client'] = ironic_discoverd.client
    if 'ironic.drivers.modules.discoverd' in sys.modules:
        reload(sys.modules['ironic.drivers.modules.discoverd'])
