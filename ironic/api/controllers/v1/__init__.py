# vim: tabstop=4 shiftwidth=4 softtabstop=4

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

"""
Version 1 of the Ironic API

NOTE: IN PROGRESS AND NOT FULLY IMPLEMENTED.

Should maintain feature parity with Nova Baremetal Extension.

Specification can be found at ironic/doc/api/v1.rst
"""

from ironic.api.controllers.v1 import controller
from ironic.api.controllers.v1 import node


Controller = controller.Controller
NodesController = node.NodesController

__all__ = (Controller,
           NodesController,)
