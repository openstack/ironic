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
    seamicroclient
    ipminative
    proliantutils
    pysnmp
"""

import sys

import mock
from oslo.utils import importutils

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
    mock_proliant_utils = mock.MagicMock()
    sys.modules['proliantutils'] = mock_proliant_utils

if 'ironic.drivers.ilo' in sys.modules:
    reload(sys.modules['ironic.drivers.ilo'])


# attempt to load the external 'pywsman' library, which is required by
# the optional drivers.modules.drac module
pywsman = importutils.try_import('pywsman')
if not pywsman:
    pywsman = mock.Mock()
    sys.modules['pywsman'] = pywsman

# if anything has loaded the drac driver yet, reload it now that the
# external library has been mocked
if 'ironic.drivers.modules.drac' in sys.modules:
    reload(sys.modules['ironic.drivers.modules.drac'])


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
