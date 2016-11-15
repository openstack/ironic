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

from oslo_config import cfg
from oslo_log import log
from oslo_messaging import exceptions as oslo_msg_exc
from oslo_versionedobjects import exception as oslo_vo_exc

from ironic.common import exception
from ironic.common.i18n import _
from ironic.objects import fields
from ironic.objects import node as node_objects
from ironic.objects import notification

LOG = log.getLogger(__name__)
CONF = cfg.CONF


def _emit_conductor_node_notification(task, notification_method,
                                      payload_method, action,
                                      level, status, **kwargs):
    """Helper for emitting a conductor notification about a node.

    :param task: a TaskManager instance.
    :param notification_method: Constructor for the notification itself.
    :param payload_method: Constructor for the notification payload. Node
                           should be first argument of the method.
    :param action: Action string to go in the EventType.
    :param level: Notification level. One of
                  `ironic.objects.fields.NotificationLevel.ALL`
    :param status: Status to go in the EventType. One of
                   `ironic.objects.fields.NotificationStatus.ALL`
    :param **kwargs: kwargs to use when creating the notification payload.
                     Passed to the payload_method.
    """
    try:
        # Prepare our exception message just in case
        exception_values = {"node": task.node.uuid,
                            "action": action,
                            "status": status,
                            "level": level,
                            "notification_method":
                                notification_method.__name__,
                            "payload_method": payload_method.__name__}
        exception_message = (_("Failed to send baremetal.node."
                               "%(action)s.%(status)s notification for node "
                               "%(node)s with level %(level)s, "
                               "notification_method %(notification_method)s, "
                               "payload_method %(payload_method)s, error "
                               "%(error)s"))
        payload = payload_method(task.node, **kwargs)
        notification.mask_secrets(payload)
        notification_method(
            publisher=notification.NotificationPublisher(
                service='ironic-conductor', host=CONF.host),
            event_type=notification.EventType(
                object='node', action=action, status=status),
            level=level,
            payload=payload).emit(task.context)
    except (exception.NotificationSchemaObjectError,
            exception.NotificationSchemaKeyError,
            exception.NotificationPayloadError,
            oslo_msg_exc.MessageDeliveryFailure,
            oslo_vo_exc.VersionedObjectsException) as e:
        exception_values['error'] = e
        LOG.warning(exception_message, exception_values)
    except Exception as e:
        # NOTE(mariojv) For unknown exceptions, also log the traceback.
        exception_values['error'] = e
        LOG.exception(exception_message, exception_values)


def emit_power_set_notification(task, level, status, to_power):
    """Helper for conductor sending a set power state notification.

    :param task: a TaskManager instance.
    :param level: Notification level. One of
                  `ironic.objects.fields.NotificationLevel.ALL`
    :param status: Status to go in the EventType. One of
                   `ironic.objects.fields.NotificationStatus.SUCCESS` or ERROR.
                   ERROR indicates that ironic-conductor couldn't retrieve the
                   power state for this node, or that it couldn't set the power
                   state of the node.
    :param to_power: the power state the conductor is
                     attempting to set on the node. This is used
                     instead of the node's target_power_state
                     attribute since the "baremetal.node.power_set.start"
                     notification is sent early, before target_power_state
                     is set on the node.
    """
    _emit_conductor_node_notification(
        task,
        node_objects.NodeSetPowerStateNotification,
        node_objects.NodeSetPowerStatePayload,
        'power_set',
        level,
        status,
        to_power=to_power
    )


def emit_power_state_corrected_notification(task, from_power):
    """Helper for conductor sending a node power state corrected notification.

       When ironic detects that the actual power state on a bare metal hardware
       is different from the power state on an ironic node (DB), the ironic
       node's power state is corrected to be that of the bare metal hardware.
       A notification is emitted about this after the database is updated to
       reflect this correction.

    :param task: a TaskManager instance.
    :param from_power: the power state of the node before this change was
                       detected
    """
    _emit_conductor_node_notification(
        task,
        node_objects.NodeCorrectedPowerStateNotification,
        node_objects.NodeCorrectedPowerStatePayload,
        'power_state_corrected',
        fields.NotificationLevel.INFO,
        fields.NotificationStatus.SUCCESS,
        from_power=from_power
    )


def emit_provision_set_notification(task, level, status, prev_state,
                                    prev_target, event):
    """Helper for conductor sending a set provision state notification.

    :param task: a TaskManager instance.
    :param level: One of fields.NotificationLevel.
    :param status: One of fields.NotificationStatus.
    :param prev_state: Previous provision state.
    :param prev_target: Previous target provision state.
    :param event: FSM event that triggered provision state change.
    """
    _emit_conductor_node_notification(
        task,
        node_objects.NodeSetProvisionStateNotification,
        node_objects.NodeSetProvisionStatePayload,
        'provision_set', level, status,
        prev_state=prev_state,
        prev_target=prev_target,
        event=event
    )


def emit_console_notification(task, action, status):
    """Helper for conductor sending a set console state notification.

    :param task: a TaskManager instance.
    :param action: Action string to go in the EventType. Must be either
                   'console_set' or 'console_restore'.
    :param status: One of `ironic.objects.fields.NotificationStatus.START`,
                   END or ERROR.
    """
    if status == fields.NotificationStatus.ERROR:
        level = fields.NotificationLevel.ERROR
    else:
        level = fields.NotificationLevel.INFO

    _emit_conductor_node_notification(
        task,
        node_objects.NodeConsoleNotification,
        node_objects.NodePayload,
        action,
        level,
        status,
    )
