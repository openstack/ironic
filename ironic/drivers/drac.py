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

from ironic.common import exception
from ironic.common.i18n import _
from ironic.drivers import base
from ironic.drivers.modules.drac import management
from ironic.drivers.modules.drac import power
from ironic.drivers.modules import pxe
from ironic.openstack.common import importutils


class PXEDracDriver(base.BaseDriver):
    """Drac driver using PXE for deploy."""

    def __init__(self):
        if not importutils.try_import('pywsman'):
            raise exception.DriverLoadError(
                    driver=self.__class__.__name__,
                    reason=_('Unable to import pywsman library'))

        self.power = power.DracPower()
        self.deploy = pxe.PXEDeploy()
        self.management = management.DracManagement()
