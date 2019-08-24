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

from keystoneauth1 import exceptions as kaexception
from oslo_log import log

from ironic.common import keystone
from ironic.common import states
from ironic.conf import CONF


LOG = log.getLogger(__name__)

NOVA_API_VERSION = "2.1"
NOVA_API_MICROVERSION = '2.76'
_NOVA_ADAPTER = None


def _get_nova_adapter():
    global _NOVA_ADAPTER
    if not _NOVA_ADAPTER:
        _NOVA_ADAPTER = keystone.get_adapter(
            'nova',
            session=keystone.get_session('nova'),
            auth=keystone.get_auth('nova'),
            version=NOVA_API_VERSION)
    return _NOVA_ADAPTER


def _get_power_update_event(server_uuid, target_power_state):
    return {'name': 'power-update',
            'server_uuid': server_uuid,
            'tag': target_power_state}


def _send_event(context, event, api_version=None):
    """Sends an event to Nova conveying power state change.

    :param context:
        request context,
        instance of ironic.common.context.RequestContext
    :param event:
        A "power-update" event for nova to act upon.
    :param api_version:
        api version of nova
    :returns:
        A boolean which indicates if the event was sent and received
        successfully.
    """

    try:
        nova = _get_nova_adapter()
        response = nova.post(
            '/os-server-external-events', json={'events': [event]},
            microversion=api_version, global_request_id=context.global_id,
            raise_exc=False)
    except kaexception.ClientException as ex:
        LOG.warning('Could not connect to Nova to send a power notification, '
                    'please check configuration. %s', ex)
        return False

    try:
        if response.status_code >= 400:
            LOG.warning('Failed to notify nova on event: %s. %s.',
                        event, response.text)
            return False
        resp_event = response.json()['events'][0]
        code = resp_event['code']
    except Exception as e:
        LOG.error('Invalid response %s returned from nova for power-update '
                  'event %s. %s.', response, event, e)
        return False

    if code >= 400:
        LOG.warning('Nova event: %s returned with failed status.', resp_event)
    else:
        LOG.debug('Nova event response: %s.', resp_event)
    return True


def power_update(context, server_uuid, target_power_state):
    """Creates and sends power state change for the provided server_uuid.

    :param context:
        request context,
        instance of ironic.common.context.RequestContext
    :param server_uuid:
        The uuid of the node whose power state changed.
    :param target_power_state:
        Targeted power state change i.e "POWER_ON" or "POWER_OFF"
    :returns:
        A boolean which indicates if the power update was executed
        successfully (mainly for testing purposes).
    """
    if not CONF.nova.send_power_notifications:
        return False

    if target_power_state == states.POWER_ON:
        target_power_state = "POWER_ON"
    elif target_power_state == states.POWER_OFF:
        target_power_state = "POWER_OFF"
    else:
        LOG.error('Invalid Power State %s.', target_power_state)
        return False
    event = _get_power_update_event(server_uuid, target_power_state)
    result = _send_event(context, event, api_version=NOVA_API_MICROVERSION)
    return result
