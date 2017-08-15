Notifications
-------------

The Bare Metal service supports the emission of notifications, which are
messages sent on a message broker (like RabbitMQ or anything else supported by
the `oslo messaging library
<https://docs.openstack.org/oslo.messaging/latest/reference/notifier.html>`_) that
indicate various events which occur, such as when a node changes power states.
These can be consumed by an external service reading from the message bus. For
example, `Searchlight <https://wiki.openstack.org/wiki/Searchlight>`_ is an
OpenStack service that uses notifications to index (and make searchable)
resources from the Bare Metal service.

Notifications are disabled by default.  For a complete list of available
notifications and instructions for how to enable them, see the
:doc:`/admin/notifications`.
