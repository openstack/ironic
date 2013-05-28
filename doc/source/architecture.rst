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
functionality: core, common, and vendor:

- :term:`Core functionality` represents the minimal API for that driver type, eg.
  power on/off for a ControlDriver.
- :term:`Common functionality` represents an extended but supported API, and any
  driver which implements it must be consistent with all other driver
  implementations of that functionality. For example, if a driver supports
  enumerating PCI devices, it must return that list as well-structured JSON. In
  this case, Ironic may validate the API input's structure, but will pass it
  unaltered to the driver. This ensures compatibility for common features
  across drivers.
- :term:`Vendor functionality` allows an excemption to the API contract when a vendor
  wishes to expose unique functionality provided by their hardware and is
  unable to do so within the core or common APIs. In this case, Ironic will
  neither store nor introspect the messages passed between the API and the
  driver.

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
