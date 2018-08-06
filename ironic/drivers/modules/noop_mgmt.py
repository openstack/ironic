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

"""No-op management interface implementation."""

from oslo_log import log

from ironic.common import boot_devices
from ironic.common import exception
from ironic.common.i18n import _
from ironic.drivers import base


LOG = log.getLogger(__name__)


class NoopManagement(base.ManagementInterface):
    """No-op management interface implementation.

    Using this implementation requires the boot order to be preconfigured
    to first try PXE booting, then fall back to hard drives.
    """

    def get_properties(self):
        return {}

    def validate(self, task):
        pass

    def get_supported_boot_devices(self, task):
        return [boot_devices.PXE, boot_devices.DISK]

    def set_boot_device(self, task, device, persistent=False):
        supported = self.get_supported_boot_devices(task)
        if device not in supported:
            raise exception.InvalidParameterValue(
                _("Invalid boot device %(dev)s specified, supported are "
                  "%(supported)s.") % {'dev': device,
                                       'supported': ', '.join(supported)})
        LOG.debug('Setting boot device to %(target)s requested for node '
                  '%(node)s with noop management. Assuming the correct '
                  'boot order is already configured',
                  {'target': device, 'node': task.node.uuid})

    def get_boot_device(self, task):
        return {'boot_device': boot_devices.PXE, 'persistent': True}

    def get_sensors_data(self, task):
        raise NotImplementedError()
