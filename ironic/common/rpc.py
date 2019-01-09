# Copyright 2014 Red Hat, Inc.
# All Rights Reserved.
#
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

import oslo_messaging as messaging
from oslo_messaging.rpc import dispatcher
from osprofiler import profiler

from ironic.common import context as ironic_context
from ironic.common import exception
from ironic.conf import CONF


TRANSPORT = None
NOTIFICATION_TRANSPORT = None
SENSORS_NOTIFIER = None
VERSIONED_NOTIFIER = None

ALLOWED_EXMODS = [
    exception.__name__,
]
EXTRA_EXMODS = []


def init(conf):
    global TRANSPORT, NOTIFICATION_TRANSPORT
    global SENSORS_NOTIFIER, VERSIONED_NOTIFIER
    exmods = get_allowed_exmods()
    TRANSPORT = messaging.get_rpc_transport(conf,
                                            allowed_remote_exmods=exmods)
    NOTIFICATION_TRANSPORT = messaging.get_notification_transport(
        conf,
        allowed_remote_exmods=exmods)

    serializer = RequestContextSerializer(messaging.JsonPayloadSerializer())
    SENSORS_NOTIFIER = messaging.Notifier(NOTIFICATION_TRANSPORT,
                                          serializer=serializer)
    if conf.notification_level is None:
        VERSIONED_NOTIFIER = messaging.Notifier(NOTIFICATION_TRANSPORT,
                                                serializer=serializer,
                                                driver='noop')
    else:
        VERSIONED_NOTIFIER = messaging.Notifier(
            NOTIFICATION_TRANSPORT,
            serializer=serializer,
            topics=CONF.versioned_notifications_topics)


def cleanup():
    global TRANSPORT, NOTIFICATION_TRANSPORT
    global SENSORS_NOTIFIER, VERSIONED_NOTIFIER
    assert TRANSPORT is not None
    assert NOTIFICATION_TRANSPORT is not None
    assert SENSORS_NOTIFIER is not None
    assert VERSIONED_NOTIFIER is not None
    TRANSPORT.cleanup()
    NOTIFICATION_TRANSPORT.cleanup()
    TRANSPORT = NOTIFICATION_TRANSPORT = None
    SENSORS_NOTIFIER = VERSIONED_NOTIFIER = None


def set_defaults(control_exchange):
    messaging.set_transport_defaults(control_exchange)


def get_allowed_exmods():
    return ALLOWED_EXMODS + EXTRA_EXMODS


class RequestContextSerializer(messaging.Serializer):

    def __init__(self, base):
        self._base = base

    def serialize_entity(self, context, entity):
        if not self._base:
            return entity
        return self._base.serialize_entity(context, entity)

    def deserialize_entity(self, context, entity):
        if not self._base:
            return entity
        return self._base.deserialize_entity(context, entity)

    def serialize_context(self, context):
        _context = context.to_dict()
        prof = profiler.get()
        if prof:
            trace_info = {
                "hmac_key": prof.hmac_key,
                "base_id": prof.get_base_id(),
                "parent_id": prof.get_id()
            }
            _context.update({"trace_info": trace_info})
        return _context

    def deserialize_context(self, context):
        trace_info = context.pop("trace_info", None)
        if trace_info:
            profiler.init(**trace_info)
        return ironic_context.RequestContext.from_dict(context)


def get_transport_url(url_str=None):
    return messaging.TransportURL.parse(CONF, url_str)


def get_client(target, version_cap=None, serializer=None):
    assert TRANSPORT is not None
    serializer = RequestContextSerializer(serializer)
    return messaging.RPCClient(TRANSPORT,
                               target,
                               version_cap=version_cap,
                               serializer=serializer)


def get_server(target, endpoints, serializer=None):
    assert TRANSPORT is not None
    serializer = RequestContextSerializer(serializer)
    access_policy = dispatcher.DefaultRPCAccessPolicy
    return messaging.get_rpc_server(TRANSPORT,
                                    target,
                                    endpoints,
                                    executor='eventlet',
                                    serializer=serializer,
                                    access_policy=access_policy)


def get_sensors_notifier(service=None, host=None, publisher_id=None):
    assert SENSORS_NOTIFIER is not None
    if not publisher_id:
        publisher_id = "%s.%s" % (service, host or CONF.host)
    return SENSORS_NOTIFIER.prepare(publisher_id=publisher_id)


def get_versioned_notifier(publisher_id=None):
    assert VERSIONED_NOTIFIER is not None
    assert publisher_id is not None
    return VERSIONED_NOTIFIER.prepare(publisher_id=publisher_id)
