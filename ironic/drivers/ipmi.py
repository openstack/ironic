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
Hardware types and classic drivers for IPMI (using ipmitool).
"""

from oslo_config import cfg

from ironic.drivers import base
from ironic.drivers import generic
from ironic.drivers.modules import agent
from ironic.drivers.modules import inspector
from ironic.drivers.modules import ipmitool
from ironic.drivers.modules import iscsi_deploy
from ironic.drivers.modules import noop
from ironic.drivers.modules import pxe


CONF = cfg.CONF


class IPMIHardware(generic.GenericHardware):
    """IPMI hardware type.

    Uses ``ipmitool`` to implement power and management.
    Provides serial console implementations via ``shellinabox`` or ``socat``.
    """

    @property
    def supported_console_interfaces(self):
        """List of supported console interfaces."""
        return [ipmitool.IPMISocatConsole, ipmitool.IPMIShellinaboxConsole,
                noop.NoConsole]

    @property
    def supported_management_interfaces(self):
        """List of supported management interfaces."""
        return [ipmitool.IPMIManagement]

    @property
    def supported_power_interfaces(self):
        """List of supported power interfaces."""
        return [ipmitool.IPMIPower]

    @property
    def supported_vendor_interfaces(self):
        """List of supported vendor interfaces."""
        return [ipmitool.VendorPassthru, noop.NoVendor]


def _to_hardware_type():
    # NOTE(dtantsur): classic drivers are not affected by the
    # enabled_inspect_interfaces configuration option.
    if CONF.inspector.enabled:
        inspect_interface = 'inspector'
    else:
        inspect_interface = 'no-inspect'

    return {'boot': 'pxe',
            'inspect': inspect_interface,
            'management': 'ipmitool',
            'power': 'ipmitool',
            'raid': 'agent',
            'vendor': 'ipmitool'}


class PXEAndIPMIToolDriver(base.BaseDriver):
    """PXE + IPMITool driver.

    This driver implements the `core` functionality, combining
    :class:`ironic.drivers.modules.ipmitool.IPMIPower` for power on/off
    and reboot with
    :class:`ironic.drivers.modules.iscsi_deploy.ISCSIDeploy` for
    image deployment. Implementations are in those respective
    classes; this class is merely the glue between them.
    """
    def __init__(self):
        self.power = ipmitool.IPMIPower()
        self.console = ipmitool.IPMIShellinaboxConsole()
        self.boot = pxe.PXEBoot()
        self.deploy = iscsi_deploy.ISCSIDeploy()
        self.management = ipmitool.IPMIManagement()
        self.inspect = inspector.Inspector.create_if_enabled(
            'PXEAndIPMIToolDriver')
        self.vendor = ipmitool.VendorPassthru()
        self.raid = agent.AgentRAID()

    @classmethod
    def to_hardware_type(cls):
        return 'ipmi', dict(_to_hardware_type(),
                            console='ipmitool-shellinabox',
                            deploy='iscsi')


class PXEAndIPMIToolAndSocatDriver(PXEAndIPMIToolDriver):
    """PXE + IPMITool + socat driver.

    This driver implements the `core` functionality, combining
    :class:`ironic.drivers.modules.ipmitool.IPMIPower` for power on/off
    and reboot with
    :class:`ironic.drivers.modules.iscsi_deploy.ISCSIDeploy` (for
    image deployment) and with
    :class:`ironic.drivers.modules.ipmitool.IPMISocatConsole`.
    This driver uses the socat console interface instead of the shellinabox
    one.
    Implementations are in those respective
    classes; this class is merely the glue between them.
    """
    def __init__(self):
        PXEAndIPMIToolDriver.__init__(self)
        self.console = ipmitool.IPMISocatConsole()

    @classmethod
    def to_hardware_type(cls):
        return 'ipmi', dict(_to_hardware_type(),
                            console='ipmitool-socat',
                            deploy='iscsi')


class AgentAndIPMIToolDriver(base.BaseDriver):
    """Agent + IPMITool driver.

    This driver implements the `core` functionality, combining
    :class:`ironic.drivers.modules.ipmitool.IPMIPower` (for power on/off and
    reboot) with :class:`ironic.drivers.modules.agent.AgentDeploy` (for
    image deployment).
    Implementations are in those respective classes; this class is merely the
    glue between them.
    """

    def __init__(self):
        self.power = ipmitool.IPMIPower()
        self.boot = pxe.PXEBoot()
        self.deploy = agent.AgentDeploy()
        self.management = ipmitool.IPMIManagement()
        self.console = ipmitool.IPMIShellinaboxConsole()
        self.vendor = ipmitool.VendorPassthru()
        self.raid = agent.AgentRAID()
        self.inspect = inspector.Inspector.create_if_enabled(
            'AgentAndIPMIToolDriver')

    @classmethod
    def to_hardware_type(cls):
        return 'ipmi', dict(_to_hardware_type(),
                            console='ipmitool-shellinabox',
                            deploy='direct')


class AgentAndIPMIToolAndSocatDriver(AgentAndIPMIToolDriver):
    """Agent + IPMITool + socat driver.

    This driver implements the `core` functionality, combining
    :class:`ironic.drivers.modules.ipmitool.IPMIPower` (for power on/off and
    reboot) with :class:`ironic.drivers.modules.agent.AgentDeploy` (for
    image deployment) and with
    :class:`ironic.drivers.modules.ipmitool.IPMISocatConsole`.
    This driver uses the socat console interface instead of the shellinabox
    one.
    Implementations are in those respective classes; this class is merely the
    glue between them.
    """

    def __init__(self):
        AgentAndIPMIToolDriver.__init__(self)
        self.console = ipmitool.IPMISocatConsole()

    @classmethod
    def to_hardware_type(cls):
        return 'ipmi', dict(_to_hardware_type(),
                            console='ipmitool-socat',
                            deploy='direct')
