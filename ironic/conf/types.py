# Licensed under the Apache License, Version 2.0 (the "License"); you may not
# use this file except in compliance with the License. You may obtain a copy
# of the License at
#
# http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
import os

from oslo_config import types


class ExplicitAbsolutePath(types.ConfigType):
    """Explicit Absolute path type.

    Absolute path values do not get transformed and are returned as
    strings. They are validated to ensure they are absolute paths and are equal
    to os.path.abspath(value) -- protecting from path traversal issues.

    Python path libraries generally define "absolute path" as anything
    starting with a /, so tools like path.PurePath(str).is_absolute() is not
    useful, because it will happily return that /tmp/../etc/resolv.conf is
    absolute. This type is to be used in cases where we require the path to
    be explicitly absolute.

    :param type_name: Type name to be used in the sample config file.
    """

    def __init__(self, type_name='explicit absolute path'):
        super().__init__(type_name=type_name)

    def __call__(self, value):
        value = str(value)

        # NOTE(JayF): This removes trailing / if provided, since
        # os.path.abspath will not return a trailing slash.
        if len(value) > 1:
            value = value.rstrip('/')
        absvalue = os.path.abspath(value)
        if value != absvalue:
            raise ValueError('Value must be an absolute path '
                             'containing no path traversal mechanisms. Config'
                             f'item was: {value}, but resolved to {absvalue}')

        return value

    def __repr__(self):
        return 'explicit absolute path'

    def _formatter(self, value):
        return self.quote_trailing_and_leading_space(value)
