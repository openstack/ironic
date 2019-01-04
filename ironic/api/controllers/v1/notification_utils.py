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

import contextlib

from oslo_config import cfg
from oslo_log import log
from oslo_messaging import exceptions as oslo_msg_exc
from oslo_utils import excutils
from oslo_versionedobjects import exception as oslo_vo_exc
from wsme import types as wtypes

from ironic.common import exception
from ironic.common.i18n import _
from ironic.objects import allocation as allocation_objects
from ironic.objects import chassis as chassis_objects
from ironic.objects import deploy_template as deploy_template_objects
from ironic.objects import fields
from ironic.objects import node as node_objects
from ironic.objects import notification
from ironic.objects import port as port_objects
from ironic.objects import portgroup as portgroup_objects
from ironic.objects import volume_connector as volume_connector_objects
from ironic.objects import volume_target as volume_target_objects

LOG = log.getLogger(__name__)
CONF = cfg.CONF


CRUD_NOTIFY_OBJ = {
    'allocation': (allocation_objects.AllocationCRUDNotification,
                   allocation_objects.AllocationCRUDPayload),
    'chassis': (chassis_objects.ChassisCRUDNotification,
                chassis_objects.ChassisCRUDPayload),
    'deploytemplate': (deploy_template_objects.DeployTemplateCRUDNotification,
                       deploy_template_objects.DeployTemplateCRUDPayload),
    'node': (node_objects.NodeCRUDNotification,
             node_objects.NodeCRUDPayload),
    'port': (port_objects.PortCRUDNotification,
             port_objects.PortCRUDPayload),
    'portgroup': (portgroup_objects.PortgroupCRUDNotification,
                  portgroup_objects.PortgroupCRUDPayload),
    'volumeconnector':
        (volume_connector_objects.VolumeConnectorCRUDNotification,
         volume_connector_objects.VolumeConnectorCRUDPayload),
    'volumetarget':
        (volume_target_objects.VolumeTargetCRUDNotification,
         volume_target_objects.VolumeTargetCRUDPayload),
}


def _emit_api_notification(context, obj, action, level, status, **kwargs):
    """Helper for emitting API notifications.

    :param context: request context.
    :param obj: resource rpc object.
    :param action: Action string to go in the EventType.
    :param level: Notification level. One of
                  `ironic.objects.fields.NotificationLevel.ALL`
    :param status: Status to go in the EventType. One of
                   `ironic.objects.fields.NotificationStatus.ALL`
    :param kwargs: kwargs to use when creating the notification payload.
    """
    resource = obj.__class__.__name__.lower()
    # value wsme.Unset can be passed from API representation of resource
    extra_args = {k: (v if v != wtypes.Unset else None)
                  for k, v in kwargs.items()}
    try:
        try:
            if action == 'maintenance_set':
                notification_method = node_objects.NodeMaintenanceNotification
                payload_method = node_objects.NodePayload
            elif resource not in CRUD_NOTIFY_OBJ:
                notification_name = payload_name = _("is not defined")
                raise KeyError(_("Unsupported resource: %s") % resource)
            else:
                notification_method, payload_method = CRUD_NOTIFY_OBJ[resource]

            notification_name = notification_method.__name__
            payload_name = payload_method.__name__
        finally:
            # Prepare our exception message just in case
            exception_values = {"resource": resource,
                                "uuid": obj.uuid,
                                "action": action,
                                "status": status,
                                "level": level,
                                "notification_method": notification_name,
                                "payload_method": payload_name}
            exception_message = (_("Failed to send baremetal.%(resource)s."
                                   "%(action)s.%(status)s notification for "
                                   "%(resource)s %(uuid)s with level "
                                   "%(level)s, notification method "
                                   "%(notification_method)s, payload method "
                                   "%(payload_method)s, error %(error)s"))

        payload = payload_method(obj, **extra_args)
        if resource == 'node':
            notification.mask_secrets(payload)
        notification_method(
            publisher=notification.NotificationPublisher(
                service='ironic-api', host=CONF.host),
            event_type=notification.EventType(
                object=resource, action=action, status=status),
            level=level,
            payload=payload).emit(context)
    except (exception.NotificationSchemaObjectError,
            exception.NotificationSchemaKeyError,
            exception.NotificationPayloadError,
            oslo_msg_exc.MessageDeliveryFailure,
            oslo_vo_exc.VersionedObjectsException) as e:
        exception_values['error'] = e
        LOG.warning(exception_message, exception_values)
    except Exception as e:
        exception_values['error'] = e
        LOG.exception(exception_message, exception_values)


def emit_start_notification(context, obj, action, **kwargs):
    """Helper for emitting API 'start' notifications.

    :param context: request context.
    :param obj: resource rpc object.
    :param action: Action string to go in the EventType.
    :param kwargs: kwargs to use when creating the notification payload.
    """
    _emit_api_notification(context, obj, action,
                           fields.NotificationLevel.INFO,
                           fields.NotificationStatus.START,
                           **kwargs)


@contextlib.contextmanager
def handle_error_notification(context, obj, action, **kwargs):
    """Context manager to handle any error notifications.

    :param context: request context.
    :param obj: resource rpc object.
    :param action: Action string to go in the EventType.
    :param kwargs: kwargs to use when creating the notification payload.
    """
    try:
        yield
    except Exception:
        with excutils.save_and_reraise_exception():
            _emit_api_notification(context, obj, action,
                                   fields.NotificationLevel.ERROR,
                                   fields.NotificationStatus.ERROR,
                                   **kwargs)


def emit_end_notification(context, obj, action, **kwargs):
    """Helper for emitting API 'end' notifications.

    :param context: request context.
    :param obj: resource rpc object.
    :param action: Action string to go in the EventType.
    :param kwargs: kwargs to use when creating the notification payload.
    """
    _emit_api_notification(context, obj, action,
                           fields.NotificationLevel.INFO,
                           fields.NotificationStatus.END,
                           **kwargs)
