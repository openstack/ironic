===============================================
Drivers, Hardware Types and Hardware Interfaces
===============================================

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

  drivers/ibmc
  drivers/idrac
  drivers/ilo
  drivers/intel-ipmi
  drivers/ipmitool
  drivers/irmc
  drivers/redfish
  drivers/snmp
  drivers/xclarity

Changing Hardware Types and Interfaces
--------------------------------------

Hardware types and interfaces are enabled in the configuration as described in
:doc:`/install/enabling-drivers`. Usually, a hardware type is configured on
enrolling as described in :doc:`/install/enrollment`::

    baremetal node create --driver <hardware type>

Any hardware interfaces can be specified on enrollment as well::

    baremetal node create --driver <hardware type> \
        --deploy-interface direct --<other>-interface <other implementation>

For the remaining interfaces the default value is assigned as described in
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
not compatible with them. There are three ways to deal with this situation:

#. Provide new values for all incompatible interfaces, for example::

    baremetal node set test --driver ipmi \
        --boot-interface pxe \
        --deploy-interface iscsi \
        --management-interface ipmitool \
        --power-interface ipmitool

#. Request resetting some of the interfaces to their new defaults by using the
   ``--reset-<IFACE>-interface`` family of arguments, for example::

    baremetal node set test --driver ipmi \
        --reset-boot-interface \
        --reset-deploy-interface \
        --reset-management-interface \
        --reset-power-interface

   .. note:: This feature is available starting with ironic 11.1.0 (Rocky
             series, API version 1.45).

#. Request resetting all interfaces to their new defaults::

    baremetal node set test --driver ipmi --reset-interfaces

   You can still specify explicit values for some interfaces::

    baremetal node set test --driver ipmi --reset-interfaces \
        --deploy-interface direct

   .. note:: This feature is available starting with ironic 11.1.0 (Rocky
             series, API version 1.45).

.. _static-boot-order:

Static boot order configuration
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Some hardware is known to misbehave when changing the boot device through the
BMC. To work around it you can use the ``noop`` management interface
implementation with the ``ipmi`` and ``redfish`` hardware types. In this case
the Bare Metal service will not change the boot device for you, leaving
the pre-configured boot order.

For example, in case of the :ref:`pxe-boot`:

#. Via any available means configure the boot order on the node as follows:

   #. Boot from PXE/iPXE on the provisioning NIC.

      .. warning::
         If it is not possible to limit network boot to only provisioning NIC,
         make sure that no other DHCP/PXE servers are accessible by the node.

   #. Boot from hard drive.

#. Make sure the ``noop`` management interface is enabled, for example:

   .. code-block:: ini

    [DEFAULT]
    enabled_hardware_types = ipmi,redfish
    enabled_management_interfaces = ipmitool,redfish,noop

#. Change the node to use the ``noop`` management interface::

      baremetal node set <NODE> --management-interface noop

Unsupported drivers
-------------------

The following drivers were declared as unsupported in ironic Newton release
and as of Ocata release they are removed from ironic:

- AMT driver - available as part of ironic-staging-drivers_
- iBoot driver - available as part of ironic-staging-drivers_
- Wake-On-Lan driver - available as part of ironic-staging-drivers_
- Virtualbox drivers
- SeaMicro drivers
- MSFT OCS drivers

The SSH drivers were removed in the Pike release. Similar functionality can be
achieved either with VirtualBMC_ or using libvirt drivers from
ironic-staging-drivers_.

.. _ironic-staging-drivers: http://ironic-staging-drivers.readthedocs.io
.. _VirtualBMC: https://opendev.org/openstack/virtualbmc
