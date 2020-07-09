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
from ironic.api.controllers import link

ID_VERSION1 = 'v1'


def all_versions():
    return [default_version()]


def default_version():
    """Return a dict representing the current default version

    id: The ID of the (major) version, also acts as the release number
    links: A list containing one link that points to the current version
    of the API

    status: Status of the version, one of CURRENT, SUPPORTED, DEPRECATED

    min_version: The current, maximum supported (major.minor) version of API.

    version: Minimum supported (major.minor) version of API.
    """

    # NOTE(dtantsur): avoid circular imports
    from ironic.api.controllers.v1 import versions

    return {
        'id': ID_VERSION1,
        'links': [
            link.make_link('self',
                           api.request.public_url,
                           ID_VERSION1, '', bookmark=True)
        ],
        'status': 'CURRENT',
        'min_version': versions.min_version_string(),
        'version': versions.max_version_string()
    }
