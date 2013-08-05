.. _architecture:

===================
System Architecture
===================

High Level description
======================

An Ironic deployment will be composed of the following components:

- A RESTful `API service`_, by which operators and other services may interact
  with the managed bare metal servers.
- A `Conductor service`_, which does the bulk of the work. Functionality is
  exposed via the `API service`_.  The Conductor and API services communicate via
  RPC.
- A Database and `DB API`_ for storing the state of the Conductor and Drivers.
- A Deployment Ramdisk or Deployment Agent, which provide control over the
  hardware which is not available remotely to the Conductor.  A ramdisk should be
  built which contains one of these agents, eg. with `diskimage-builder`_.
  This ramdisk can be booted on-demand.

    - **NOTE:** The agent is never run inside a tenant instance.

Drivers
=======

The internal driver API provides a consistent interface between the
Conductor service and the driver implementations. A driver is defined by
a class inheriting from the `BaseDriver`_ class, defining certain interfaces;
each interface is an instance of the relevant driver module.

For example, a fake driver class might look like this::

    class FakePower(base.PowerInterface):
        def get_power_state(self, task, node):
            return states.NOSTATE

        def set_power_state(self, task, node, power_state):
            pass

    class FakeDriver(base.BaseDriver):
        def __init__(self):
            self.power = FakePower()


There are three categories of driver interfaces:

- `Core` interfaces provide the essential functionality for Ironic within
  OpenStack, and may be depended upon by other services. All drivers
  must implement these interfaces. Presently, the Core interfaces are power and deploy.
- `Standard` interfaces provide functionality beyond the needs of OpenStack,
  but which has been standardized across all drivers and becomes part of
  Ironic's API.  If a driver implements this interface, it must adhere to the
  standard. This is presented to encourage vendors to work together with the
  Ironic project and implement common features in a consistent way, thus
  reducing the burden on consumers of the API.
  Presently, the Standard interfaces are rescue and console.
- The `Vendor` interface allows an exemption to the API contract when a vendor
  wishes to expose unique functionality provided by their hardware and is
  unable to do so within the core or standard interfaces. In this case, Ironic
  will merely relay the message from the API service to the appropriate driver.


.. _API service: /api/ironic.api.controllers.v1.html
.. _BaseDriver: /api/ironic.drivers.base.html#ironic.drivers.base.BaseDriver
.. _Conductor service: /api/ironic.conductor.manager.html
.. _DB API: /api/ironic.db.api.html
.. _diskimage-builder: https://github.com/stackforge/diskimage-builder
