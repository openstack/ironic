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
"""WSGI script for Ironic API, installed by pbr."""

import sys

from oslo_config import cfg
from oslo_log import log

from ironic.api import app
from ironic.common import i18n
from ironic.common import service


CONF = cfg.CONF
LOG = log.getLogger(__name__)


# NOTE(dtantsur): WSGI containers may need to override the passed argv.
def initialize_wsgi_app(argv=sys.argv):
    i18n.install('ironic')

    service.prepare_command(argv)

    LOG.debug("Configuration:")
    CONF.log_opt_values(LOG, log.DEBUG)

    return app.VersionSelectorApplication()
