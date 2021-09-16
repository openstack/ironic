.. _pluggable_drivers:

=================
Pluggable Drivers
=================

Ironic supports a pluggable driver model. This allows contributors to easily
add new drivers, and operators to use third-party drivers or write their own.
A driver is built at runtime from a *hardware type* and *hardware interfaces*.
See :doc:`/install/enabling-drivers` for a detailed explanation of these
concepts.

Hardware types and interfaces are loaded by the ``ironic-conductor`` service
during initialization from the setuptools entrypoints ``ironic.hardware.types``
and ``ironic.hardware.interfaces.<INTERFACE>`` where ``<INTERFACE>`` is an
interface type (for example, ``deploy``). Only hardware types listed in the
configuration option ``enabled_hardware_types`` and interfaces listed in
configuration options ``enabled_<INTERFACE>_interfaces`` are loaded.
A complete list of hardware types available on the system may be found by
enumerating this entrypoint by running the following python script::

  #!/usr/bin/env python

  import pkg_resources as pkg
  print [p.name for p in pkg.iter_entry_points("ironic.hardware.types") if not p.name.startswith("fake")]

A list of drivers enabled in a running Ironic service may be found by issuing
the following command against that API end point::

  baremetal driver list

Writing a hardware type
-----------------------

A hardware type is a Python class, inheriting
:py:class:`ironic.drivers.hardware_type.AbstractHardwareType` and listed in
the setuptools entry point ``ironic.hardware.types``. Most of the real world
hardware types inherit :py:class:`ironic.drivers.generic.GenericHardware`
instead. This helper class provides useful implementations for interfaces that
are usually the same for all hardware types, such as ``deploy``.

The minimum required interfaces are:

* :doc:`boot </admin/interfaces/boot>` that specifies how to boot ramdisks and
  instances on the hardware. A generic ``pxe`` implementation is provided
  by the ``GenericHardware`` base class.

* :doc:`deploy </admin/interfaces/deploy>` that orchestrates the deployment.
  A few common implementations are provided by the ``GenericHardware`` base
  class.

  As of the Rocky release, a deploy interface should decorate its deploy method
  to indicate that it is a deploy step. Conventionally, the deploy method uses
  a priority of 100.

  .. code-block:: python

     @ironic.drivers.base.deploy_step(priority=100)
     def deploy(self, task):

  .. note::
    Most of the hardware types should not override this interface.

* `power` implements power actions for the hardware. These common
  implementations may be used, if supported by the hardware:

  * :py:class:`ironic.drivers.modules.ipmitool.IPMIPower`
  * :py:class:`ironic.drivers.modules.redfish.power.RedfishPower`

  Otherwise, you need to write your own implementation by subclassing
  :py:class:`ironic.drivers.base.PowerInterface` and providing missing methods.

  .. note::
    Power actions in Ironic are blocking - methods of a power interface should
    not return until the power action is finished or errors out.

* `management` implements additional out-of-band management actions, such as
  setting a boot device. A few common implementations exist and may be used,
  if supported by the hardware:

  * :py:class:`ironic.drivers.modules.ipmitool.IPMIManagement`
  * :py:class:`ironic.drivers.modules.redfish.management.RedfishManagement`

  Some hardware types, such as ``snmp`` do not support out-of-band management.
  They use the fake implementation in
  :py:class:`ironic.drivers.modules.fake.FakeManagement` instead.

  Otherwise, you need to write your own implementation by subclassing
  :py:class:`ironic.drivers.base.ManagementInterface` and providing missing
  methods.

Combine the interfaces in a hardware type by populating the lists of
supported interfaces. These lists are prioritized, with the most preferred
implementation first. For example:

.. code-block:: python

    class MyHardware(generic.GenericHardware):

        @property
        def supported_management_interfaces(self):
            """List of supported management interfaces."""
            return [MyManagement, ipmitool.IPMIManagement]

        @property
        def supported_power_interfaces(self):
            """List of supported power interfaces."""
            return [MyPower, ipmitool.IPMIPower]

.. note::
    In this example, all interfaces, except for ``management`` and ``power``
    are taken from the ``GenericHardware`` base class.

Finally, give the new hardware type and new interfaces human-friendly names and
create entry points for them in the ``setup.cfg`` file::

    ironic.hardware.types =
        my-hardware = ironic.drivers.my_hardware:MyHardware
    ironic.hardware.interfaces.power =
        my-power = ironic.drivers.modules.my_hardware:MyPower
    ironic.hardware.interfaces.management =
        my-management = ironic.drivers.modules.my_hardware:MyManagement

Deploy and clean steps
----------------------

Significant parts of the bare metal functionality is implemented via
:doc:`deploy steps </admin/node-deployment>` or :doc:`clean steps
</admin/cleaning>`. See :doc:`deploy-steps` for information on how to write
them.

Supported Drivers
-----------------

For a list of supported drivers (those that are continuously tested on every
upstream commit) please consult the :doc:`drivers page </admin/drivers>`.
