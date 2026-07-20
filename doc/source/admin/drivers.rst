.. meta::
   :description: Comprehensive guide to Ironic hardware drivers and interfaces. Configure support for IPMI, Redfish, vendor-specific management, and hardware types.
   :keywords: ironic drivers, hardware interfaces, IPMI, redfish, hardware management, vendor drivers, boot interfaces, power management
   :author: OpenStack Ironic Team
   :robots: index, follow
   :audience: system administrators, hardware engineers

===========================================================
Drivers, Hardware Types, and Hardware Interfaces for Ironic
===========================================================

Before configuring Ironic, it helps to understand three closely related
concepts: *hardware interfaces*, *hardware types*, and *drivers*.

Hardware interfaces
~~~~~~~~~~~~~~~~~~~

A **hardware interface** (often just called an *interface*) implements one of
the operational abstractions that Ironic needs to perform against hardware.
Each interface covers a single category of operations. For example, the
``power`` interface defines the operations needed to control a node's power
state, and the ``boot`` interface defines the operations needed to boot a
node. Ironic defines a number of these interfaces, including ``power``,
``boot``, ``deploy``, ``management``, ``inspect``, and more.

A given category of operation can usually be carried out in more than one way.
Managing a node's power, for instance, might be done over the Redfish protocol
or over IPMI. Each of these is a separate *implementation* of the ``power``
interface (for example, ``redfish`` and ``ipmitool``).

Hardware types
~~~~~~~~~~~~~~

A **hardware type** describes a class of hardware in terms of the interface
implementations it is able to support. It does not, by itself, pick which
implementation is used; instead it declares the set of compatible options for
each interface. For example, a hardware type might report that it supports both
the ``redfish`` and ``ipmitool`` implementations of the ``power`` interface,
leaving the actual choice to be made later.

Drivers
~~~~~~~

A **driver** is a hardware type as it has been loaded and configured for use.
Where a hardware type offers a menu of compatible interface implementations, a
driver is the fully-resolved result of selecting exactly one implementation for
each interface — one ``power`` implementation, one ``boot`` implementation, and
so on. In short: the hardware type says what is *possible*, and the driver
captures what has actually been *chosen* for a node.

The rest of this document describes the interfaces and hardware types Ironic
ships with, and how to select and change them.

Generic Interfaces
------------------

.. toctree::
  :maxdepth: 2

  interfaces/boot
  interfaces/deploy

Hardware Types
--------------

.. toctree::
  :maxdepth: 1

  drivers/idrac
  drivers/intel-ipmi
  drivers/ipmitool
  drivers/redfish
  drivers/fake

Changing Hardware Types and Interfaces
--------------------------------------

Hardware types and interfaces are enabled in the configuration as described in
:doc:`/install/enabling-drivers`. Usually, a hardware type is configured on
enrolling as described in :doc:`/install/enrollment`::

    baremetal node create --driver <hardware type>

Any hardware interfaces can be specified on enrollment as well::

    baremetal node create --driver <hardware type> \
        --deploy-interface direct --<other>-interface <other implementation>

For the remaining interfaces, the default value is assigned as described in
:ref:`hardware_interfaces_defaults`. Both the hardware type and the hardware
interfaces can be changed later via the node update API.

Changing Hardware Interfaces
~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Hardware interfaces can be changed by the following command::

    baremetal node set <NODE> \
        --deploy-interface direct \
        --<other>-interface <other implementation>

The modified interfaces must be enabled and compatible with the current node's
hardware type.

Changing Hardware Type
~~~~~~~~~~~~~~~~~~~~~~

Changing the node's hardware type can pose a problem. When the ``driver``
field is updated, the final result must be consistent, that is, the resulting
hardware interfaces must be compatible with the new hardware type. This will
not work::

    baremetal node create --name test --driver fake-hardware
    baremetal node set test --driver ipmi

This is because the ``fake-hardware`` hardware type defaults to ``fake``
implementations for some or all interfaces, but the ``ipmi`` hardware type is
incompatible with them. There are three ways to deal with this situation:

#. Provide new values for all incompatible interfaces, for example::

    baremetal node set test --driver ipmi \
        --boot-interface pxe \
        --deploy-interface direct \
        --management-interface ipmitool \
        --power-interface ipmitool

#. Request resetting some of the interfaces to their new defaults by using the
   ``--reset-<IFACE>-interface`` family of arguments, for example::

    baremetal node set test --driver ipmi \
        --reset-boot-interface \
        --reset-deploy-interface \
        --reset-management-interface \
        --reset-power-interface

#. Request resetting all interfaces to their new defaults::

    baremetal node set test --driver ipmi --reset-interfaces

   You can still specify explicit values for some interfaces::

    baremetal node set test --driver ipmi --reset-interfaces \
        --deploy-interface direct

.. _static-boot-order:

Static boot order configuration
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Some hardware is known to misbehave when changing the boot device through the
BMC. To work around it you can use the ``noop`` management interface
implementation with the ``ipmi`` and ``redfish`` hardware types. In this case
the Bare Metal service will not change the boot device for you, leaving
the pre-configured boot order.

For example, in the case of the :ref:`pxe-boot`:

#. Via any available means configure the boot order on the node as follows:

   #. Boot from PXE/iPXE on the provisioning NIC.

      .. warning::
         If it is not possible to limit network boot to only provisioning NIC,
         make sure that no other DHCP/PXE servers are accessible by the node.

   #. Boot from the hard drive.

#. Make sure the ``noop`` management interface is enabled, for example:

   .. code-block:: ini

    [DEFAULT]
    enabled_hardware_types = ipmi,redfish
    enabled_management_interfaces = ipmitool,redfish,noop

#. Change the node to use the ``noop`` management interface::

      baremetal node set <NODE> --management-interface noop
