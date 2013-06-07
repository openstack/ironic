.. _architecture:

===================
System Architecture
===================

High Level description
======================

An Ironic deployment will be composed of the following components:

- A RESTful `API service`_, by which operators and other services may interact
  with the managed bare metal servers.
- A `Manager service`_, which does the bulk of the work. Functionality is
  exposed via the `API service`_.  The Manager and API services communicate via
  RPC.
- A Database and `DB API`_ for storing the state of the Manager and Drivers.
- One or more Deployment Agents, which provide local control over the
  hardware which is not available remotely to the Manager.  A ramdisk should be
  built which contains one of these agents, eg. with `diskimage-builder`_.
  This ramdisk can be booted on-demand.

    - **NOTE:** The agent is never run inside a tenant instance.

Drivers
=======

The internal driver API provides a consistent interface between the
Manager service and the driver implementations. There are two types of drivers:

- `ControlDrivers`_ manage the hardware, performing functions such as power
  on/off, toggle boot device, etc.
- `DeployDrivers`_ handle the task of booting a temporary ramdisk, formatting
  drives, and putting a persistent image onto the hardware.
- Driver implementations are loaded and instantiated via entrypoints when the
  `Manager service`_ starts. Each Node record stored in the database indicates
  which drivers should manage it. When a task is started on that node,
  information about the node and task is passed to the corresponding driver.
  In this way, heterogeneous hardware deployments can be managed by a single
  Manager service.

In addition to the two types of drivers, there are three categories of driver
functionality: core, standardized, and vendor:

- `Core functionality` represents the essential functionality for Ironic within
  OpenStack, and may be depended upon by other services. This is represented
  internally by the driver's base class definitions, and is exposed directly in
  the API in relation to the object. For example, a node's power state, which is
  a core functionality of ControlDrivers, is exposed at the URI
  "/nodes/<uuid>/state".
- `Standardized functionality` represents functionality beyond the needs of
  OpenStack, but which has been standardized across all drivers and becomes
  part of Ironic's API.  If a driver implements this, it must adhere to the
  standard. This is presented to encourage vendors to work together with the
  Ironic project and implement common features in a consistent way, thus
  reducing the burden on consumers of the API.  A ficticious example of this
  might be a means to specify the Node's next-boot device. Initially, this
  might be implemented differently by each driver, but over time it could be
  moved from "/drivers/<name>/vendor_passthrough/" to "/node/<uuid>/nextboot".
- `Vendor functionality` allows an excemption to the API contract when a vendor
  wishes to expose unique functionality provided by their hardware and is
  unable to do so within the core or standardized APIs. In this case, Ironic
  will merely relay the message from the API service to the appropriate driver.
  For example, if vendor "foo" wanted to expose a "bar" function, the URI might
  look like this: "/drivers/foo/vendor_passthrough/bar".

Default Drivers
===============

The default drivers, suitable for most deployments will be the `IPMIPowerDriver`_
and the `PXEDeployDriver`_.

Additionally, for test environments that do not have IPMI (eg., when mocking a
deployment using virtual machines), an `SSHPowerDriver`_ is also supplied.



.. _API service: api/ironic.api.controllers.v1
.. _Manager service: api/ironic.manager.manager
.. _DB API: api/ironic.db.api
.. _ControlDrivers: api/ironic.drivers.base#ironic.drivers.base.ControlDriver
.. _DeployDrivers: api/ironic.drivers.base#ironic.drivers.base.DeployDriver
.. _IPMIPowerDriver: api/ironic.drivers.ipmi#ironic.drivers.ipmi.IPMIPowerDriver
.. _PXEDeployDriver: api/ironic.drivers.pxe#ironic.drivers.pxe.PXEDeployDriver
.. _SSHPowerDriver: api/ironic.drivers.ssh#ironic.drivers.ssh.SSHPowerDriver
.. _diskimage-builder: https://github.com/stackforge/diskimage-builder
