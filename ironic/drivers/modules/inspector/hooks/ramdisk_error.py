# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#    http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or
# implied.
# See the License for the specific language governing permissions and
# limitations under the License.

from ironic.common import exception
from ironic.common.i18n import _
from ironic.drivers.modules.inspector.hooks import base


class RamdiskErrorHook(base.InspectionHook):
    """Hook to process error sent from the ramdisk."""

    def preprocess(self, task, inventory, plugin_data):
        if plugin_data.get('error'):
            msg = _("Ramdisk reported error: %(error)s") % {
                'error': plugin_data['error']}
            raise exception.HardwareInspectionFailure(error=msg)

    def __call__(self, task, inventory, plugin_data):
        pass
