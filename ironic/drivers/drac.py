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
DRAC Driver for remote system management using Dell Remote Access Card.
"""

from oslo_utils import importutils

from ironic.common import exception
from ironic.common.i18n import _
from ironic.drivers import base
from ironic.drivers.modules.drac import management
from ironic.drivers.modules.drac import power
from ironic.drivers.modules.drac import vendor_passthru
from ironic.drivers.modules import inspector
from ironic.drivers.modules import iscsi_deploy
from ironic.drivers.modules import pxe
from ironic.drivers import utils


class PXEDracDriver(base.BaseDriver):
    """Drac driver using PXE for deploy."""

    def __init__(self):
        if not importutils.try_import('dracclient'):
            raise exception.DriverLoadError(
                driver=self.__class__.__name__,
                reason=_('Unable to import python-dracclient library'))

        self.power = power.DracPower()
        self.boot = pxe.PXEBoot()
        self.deploy = iscsi_deploy.ISCSIDeploy()
        self.management = management.DracManagement()
        self.iscsi_vendor = iscsi_deploy.VendorPassthru()
        self.drac_vendor = vendor_passthru.DracVendorPassthru()
        self.mapping = {'heartbeat': self.iscsi_vendor,
                        'get_bios_config': self.drac_vendor,
                        'set_bios_config': self.drac_vendor,
                        'commit_bios_config': self.drac_vendor,
                        'abandon_bios_config': self.drac_vendor,
                        }
        self.driver_passthru_mapping = {'lookup': self.iscsi_vendor}
        self.vendor = utils.MixinVendorInterface(self.mapping,
                                                 self.driver_passthru_mapping)
        self.inspect = inspector.Inspector.create_if_enabled(
            'PXEDracDriver')
