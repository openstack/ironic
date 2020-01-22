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

from ironic import api
from ironic.api.controllers import base
from ironic.api.controllers import link

ID_VERSION1 = 'v1'


class Version(base.Base):
    """An API version representation.

    This class represents an API version, including the minimum and
    maximum minor versions that are supported within the major version.
    """

    id = str
    """The ID of the (major) version, also acts as the release number"""

    links = [link.Link]
    """A Link that point to a specific version of the API"""

    status = str
    """Status of the version.

    One of:
    * CURRENT - the latest version of API,
    * SUPPORTED - supported, but not latest, version of API,
    * DEPRECATED - supported, but deprecated, version of API.
    """

    version = str
    """The current, maximum supported (major.minor) version of API."""

    min_version = str
    """Minimum supported (major.minor) version of API."""

    def __init__(self, id, min_version, version, status='CURRENT'):
        self.id = id
        self.links = [link.Link.make_link('self', api.request.public_url,
                                          self.id, '', bookmark=True)]
        self.status = status
        self.version = version
        self.min_version = min_version


def default_version():
    # NOTE(dtantsur): avoid circular imports
    from ironic.api.controllers.v1 import versions

    return Version(ID_VERSION1,
                   versions.min_version_string(),
                   versions.max_version_string())
