.. _api-audit-support:

=================
API Audit Logging
=================

Audit middleware supports delivery of CADF audit events via Oslo messaging
notifier capability. Based on `notification_driver` configuration, audit events
can be routed to messaging infrastructure (notification_driver = messagingv2)
or can be routed to a log file (`[oslo_messaging_notifications]/driver = log`).

Audit middleware creates two events per REST API interaction. First event has
information extracted from request data and the second one has request outcome
(response).

Enabling API Audit Logging
==========================

Audit middleware is available as part of `keystonemiddleware` (>= 1.6) library.
For information regarding how audit middleware functions refer
:keystonemiddleware-doc:`here <audit.html>`.

Auditing can be enabled for the Bare Metal service by making the following changes
to ``/etc/ironic/ironic.conf``.

#. To enable audit logging of API requests::

    [audit]
    ...
    enabled=true

#. To customize auditing API requests, the audit middleware requires the audit_map_file setting
   to be defined. Update the value of configuration setting 'audit_map_file' to set its
   location. Audit map file configuration options for the Bare Metal service are included
   in the etc/ironic/ironic_api_audit_map.conf.sample file. To understand CADF format
   specified in ironic_api_audit_map.conf file refer to `CADF Format.
   <http://www.dmtf.org/sites/default/files/standards/documents/DSP2038_1.0.0.pdf>`_::

    [audit]
    ...
    audit_map_file=/etc/ironic/api_audit_map.conf

#. Comma separated list of Ironic REST API HTTP methods to be ignored during audit.
   It is used only when API audit is enabled. For example::

    [audit]
    ...
    ignore_req_list=GET,POST

Sample Audit Event
==================

Following is the sample of audit event for ironic node list request.

.. code-block:: json

    {
       "event_type":"audit.http.request",
       "timestamp":"2016-06-15 06:04:30.904397",
       "payload":{
          "typeURI":"http://schemas.dmtf.org/cloud/audit/1.0/event",
          "eventTime":"2016-06-15T06:04:30.903071+0000",
          "target":{
             "id":"ironic",
             "typeURI":"unknown",
             "addresses":[
                {
                   "url":"http://{ironic_admin_host}:6385",
                   "name":"admin"
                },
               {
                   "url":"http://{ironic_internal_host}:6385",
                   "name":"private"
               },
               {
                   "url":"http://{ironic_public_host}:6385",
                   "name":"public"
               }
             ],
             "name":"ironic"
          },
          "observer":{
             "id":"target"
          },
          "tags":[
             "correlation_id?value=685f1abb-620e-5d5d-b74a-b4135fb32373"
          ],
          "eventType":"activity",
          "initiator":{
             "typeURI":"service/security/account/user",
             "name":"admin",
             "credential":{
                "token":"***",
                "identity_status":"Confirmed"
             },
             "host":{
                "agent":"python-ironicclient",
                "address":"10.1.200.129"
             },
             "project_id":"d8f52dd7d9e1475dbbf3ba47a4a83313",
             "id":"8c1a948bad3948929aa5d5b50627a174"
          },
          "action":"read",
          "outcome":"pending",
          "id":"061b7aa7-5879-5225-a331-c002cf23cb6c",
          "requestPath":"/v1/nodes/?associated=True"
       },
       "priority":"INFO",
       "publisher_id":"ironic-api",
       "message_id":"2f61ebaa-2d3e-4023-afba-f9fca6f21fc2"
    }
