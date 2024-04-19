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

import microversion_parse as mvp
from oslo_log import log

from ironic.api.controllers import base
from ironic.api.controllers.v1 import versions
from ironic.common import utils


LOG = log.getLogger(__name__)


class JsonExtensionMiddleware(object):
    """Simplified processing of .json extension.

    Previously Ironic API used the "guess_content_type_from_ext" feature.
    It was never needed, as we never allowed non-JSON content types anyway.
    Now that it is removed, this middleware strips .json extension for
    backward compatibility.

    """
    def __init__(self, app):
        self.app = app

    def __call__(self, env, start_response):
        path = utils.safe_rstrip(env.get('PATH_INFO'), '/')

        if path and path.endswith('.json'):
            version_string = self.transform_header(base.Version.string)

            minor = None
            request_version = env.get(version_string, '')
            if request_version:
                _, minor = mvp.parse_version_string(request_version)

            env['HAS_JSON_SUFFIX'] = False
            if minor and minor < versions.MINOR_91_DOT_JSON:
                LOG.debug('Stripping .json prefix from %s for compatibility '
                          'with pecan', path)
                env['PATH_INFO'] = path[:-5]
                env['HAS_JSON_SUFFIX'] = True
        else:
            env['HAS_JSON_SUFFIX'] = False

        return self.app(env, start_response)

    def transform_header(self, version_string):
        """Transforms version string to HTTP header format."""
        return 'HTTP_%s' % version_string.replace('-', '_').upper()
