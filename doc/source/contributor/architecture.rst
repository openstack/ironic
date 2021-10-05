.. _architecture:

===================
System Architecture
===================

High Level description
======================

An Ironic deployment will be composed of the following components:

- An admin-only RESTful `API service`_, by which privileged users, such as
  cloud operators and other services within the cloud control plane, may
  interact with the managed bare metal servers.
- A `Conductor service`_, which does the bulk of the work. Functionality is
  exposed via the `API service`_.  The Conductor and API services communicate via
  RPC.
- A Database and `DB API`_ for storing the state of the Conductor and Drivers.
- A Deployment Ramdisk or Deployment Agent, which provide control over the
  hardware which is not available remotely to the Conductor.  A ramdisk should be
  built which contains one of these agents, eg. with `diskimage-builder`_.
  This ramdisk can be booted on-demand.

  .. note:: The agent is never run inside a tenant instance.

.. _`architecture_drivers`:

Drivers
=======

The internal driver API provides a consistent interface between the
Conductor service and the driver implementations. A driver is defined by
a *hardware type* deriving from the AbstractHardwareType_ class, defining
supported *hardware interfaces*. See :doc:`/install/enabling-drivers`
for a more detailed explanation. See :doc:`drivers` for an explanation on how
to write new hardware types and interfaces.

Driver-Specific Periodic Tasks
------------------------------

Drivers may run their own periodic tasks, i.e. actions run repeatedly after
a certain amount of time. Such a task is created by using the periodic_
decorator on an interface method. For example

.. code-block:: python

    from futurist import periodics

    class FakePower(base.PowerInterface):
        @periodics.periodic(spacing=42)
        def task(self, manager, context):
            pass  # do something


Here the ``spacing`` argument is a period in seconds for a given periodic task.
For example 'spacing=5' means every 5 seconds.

Starting with the Yoga cycle, there is also a new decorator
:py:func:`ironic.conductor.periodics.node_periodic` to create periodic tasks
that handle nodes. See :ref:`deploy steps documentation <deploy-steps-polling>`
for an example.

Driver-Specific Steps
---------------------

Drivers may have specific steps that may need to be executed or offered to a
user to execute in order to perform specific configuration tasks.

These steps should ideally be located on the management interface to enable
consistent user experience of the hardware type. What should be avoided is
duplication of existing interfaces such as the deploy interface to enable
vendor specific cleaning or deployment steps.

Message Routing
===============

Each Conductor registers itself in the database upon start-up, and periodically
updates the timestamp of its record. Contained within this registration is a
list of the drivers which this Conductor instance supports.  This allows all
services to maintain a consistent view of which Conductors and which drivers
are available at all times.

Based on their respective driver, all nodes are mapped across the set of
available Conductors using a `consistent hashing algorithm`_. Node-specific
tasks are dispatched from the API tier to the appropriate conductor using
conductor-specific RPC channels.  As Conductor instances join or leave the
cluster, nodes may be remapped to different Conductors, thus triggering various
driver actions such as take-over or clean-up.


.. _API service: webapi.html
.. _AbstractHardwareType: api/ironic.drivers.hardware_type.html#ironic.drivers.hardware_type.AbstractHardwareType
.. _Conductor service: api/ironic.conductor.manager.html
.. _DB API: api/ironic.db.api.html
.. _diskimage-builder: https://docs.openstack.org/diskimage-builder/latest/
.. _consistent hashing algorithm: https://docs.openstack.org/tooz/latest/user/tutorial/hashring.html
.. _periodic: https://docs.openstack.org/futurist/latest/reference/index.html#futurist.periodics.periodic
