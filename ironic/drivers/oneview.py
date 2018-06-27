# Copyright (2015-2017) Hewlett Packard Enterprise Development LP
# Copyright (2015-2017) Universidade Federal de Campina Grande
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

"""
OneView hardware type.
"""

from ironic.drivers import generic
from ironic.drivers.modules import noop
from ironic.drivers.modules.oneview import deploy
from ironic.drivers.modules.oneview import inspect
from ironic.drivers.modules.oneview import management
from ironic.drivers.modules.oneview import power


class OneViewHardware(generic.GenericHardware):
    """OneView hardware type.

    OneView hardware type is targeted for OneView
    """
    # NOTE(TheJulia): Marking as unsupported as 3rd party CI was taken down
    # shortly before the beginning of the Rocky cycle, and no replies have
    # indicated that 3rd party CI will be re-established nor visible
    # actions observed regarding re-establishing 3rd party CI.
    # TODO(TheJulia): This should be expected to be removed in Stein.
    supported = False

    @property
    def supported_deploy_interfaces(self):
        """List of supported deploy interfaces."""
        return [deploy.OneViewIscsiDeploy, deploy.OneViewAgentDeploy]

    @property
    def supported_inspect_interfaces(self):
        """List of supported inspect interfaces."""
        return [inspect.OneViewInspect, noop.NoInspect]

    @property
    def supported_management_interfaces(self):
        """List of supported management interfaces."""
        return [management.OneViewManagement]

    @property
    def supported_power_interfaces(self):
        """List of supported power interfaces."""
        return [power.OneViewPower]
