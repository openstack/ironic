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

from ironic_lib import metrics_utils
from oslo_log import log
import pecan

from ironic.api.controllers.v1 import utils as api_utils
from ironic.api import method
from ironic.common import args
from ironic.common import exception

METRICS = metrics_utils.get_metrics_logger(__name__)

LOG = log.getLogger(__name__)


NETWORK_EVENT_VALIDATOR = args.and_valid(
    args.schema({
        'type': 'object',
        'properties': {
            'event': {'type': 'string'},
            'port_id': {'type': 'string'},
            'mac_address': {'type': 'string'},
            'status': {'type': 'string'},
            'device_id': {'type': ['string', 'null']},
            'binding:host_id': {'type': ['string', 'null']},
            'binding:vnic_type': {'type': ['string', 'null']},
        },
        'required': ['event', 'port_id', 'mac_address', 'status'],
        'additionalProperties': False,
    }),
    args.dict_valid(**{
        'port_id': args.uuid,
        'mac_address': args.mac_address,
        'device_id': args.uuid,
        'binding:host_id': args.uuid
    })
)

EVENT_VALIDATORS = {
    'network.bind_port': NETWORK_EVENT_VALIDATOR,
    'network.unbind_port': NETWORK_EVENT_VALIDATOR,
    'network.delete_port': NETWORK_EVENT_VALIDATOR,
}

EVENTS_SCHEMA = {
    'type': 'object',
    'properties': {
        'events': {
            'type': 'array',
            'minItems': 1,
            'items': {
                'type': 'object',
                'properties': {
                    'event': {'type': 'string',
                              'enum': list(EVENT_VALIDATORS)},
                },
                'required': ['event'],
                'additionalProperties': True,
            },
        },
    },
    'required': ['events'],
    'additionalProperties': False,
}


def events_valid(name, value):
    """Validator for events"""

    for event in value['events']:
        validator = EVENT_VALIDATORS[event['event']]
        validator(name, event)
    return value


class EventsController(pecan.rest.RestController):
    """REST controller for Events."""

    @pecan.expose()
    def _lookup(self):
        if not api_utils.allow_expose_events():
            pecan.abort(http_client.NOT_FOUND)

    @METRICS.timer('EventsController.post')
    @method.expose(status_code=http_client.NO_CONTENT)
    @method.body('evts')
    @args.validate(evts=args.and_valid(args.schema(EVENTS_SCHEMA),
                                       events_valid))
    def post(self, evts):
        if not api_utils.allow_expose_events():
            raise exception.NotFound()
        api_utils.check_policy('baremetal:events:post')
        for e in evts['events']:
            LOG.debug("Received external event: %s", e)
