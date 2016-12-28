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

from ironic.drivers import base


class NoopStorage(base.StorageInterface):
    """No-op Storage Interface."""

    def validate(self, task):
        pass

    def get_properties(self):
        return {}

    def attach_volumes(self, task):
        pass

    def detach_volumes(self, task):
        pass

    def should_write_image(self, task):
        return True
