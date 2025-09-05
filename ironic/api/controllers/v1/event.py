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

from http import client as http_client

from oslo_log import log
import pecan

from ironic.api.controllers.v1 import utils as api_utils
from ironic.api.controllers.v1 import versions
from ironic.api import method
from ironic.api.schemas.v1 import event as schema
from ironic.api import validation
from ironic.common import metrics_utils

METRICS = metrics_utils.get_metrics_logger(__name__)

LOG = log.getLogger(__name__)


class EventsController(pecan.rest.RestController):
    """REST controller for Events."""

    @METRICS.timer('EventsController.post')
    @method.expose(status_code=http_client.NO_CONTENT)
    @method.body('evts')
    @validation.api_version(min_version=versions.MINOR_54_EVENTS)
    @validation.request_body_schema(schema.create_request_body)
    def post(self, evts):
        api_utils.check_policy('baremetal:events:post')
        for e in evts['events']:
            LOG.debug("Received external event: %s", e)
