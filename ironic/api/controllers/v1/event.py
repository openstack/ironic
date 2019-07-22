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

from ironic_lib import metrics_utils
from oslo_log import log
import pecan
from six.moves import http_client

from ironic import api
from ironic.api.controllers.v1 import collection
from ironic.api.controllers.v1 import types
from ironic.api.controllers.v1 import utils as api_utils
from ironic.api import expose
from ironic.common import exception
from ironic.common import policy

METRICS = metrics_utils.get_metrics_logger(__name__)

LOG = log.getLogger(__name__)


class EvtCollection(collection.Collection):
    """API representation of a collection of events."""

    events = [types.eventtype]
    """A list containing event dict objects"""


class EventsController(pecan.rest.RestController):
    """REST controller for Events."""

    @pecan.expose()
    def _lookup(self):
        if not api_utils.allow_expose_events():
            pecan.abort(http_client.NOT_FOUND)

    @METRICS.timer('EventsController.post')
    @expose.expose(None, body=EvtCollection,
                   status_code=http_client.NO_CONTENT)
    def post(self, evts):
        if not api_utils.allow_expose_events():
            raise exception.NotFound()
        cdict = api.request.context.to_policy_values()
        policy.authorize('baremetal:events:post', cdict, cdict)
        for e in evts.events:
            LOG.debug("Received external event: %s", e)
