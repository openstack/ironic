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

    openstack baremetal node create --driver <hardware type>

Any hardware interfaces can be specified on enrollment as well::

    openstack baremetal node create --driver <hardware type> \
        --deploy-interface direct --<other>-interface <other implementation>

For the remaining interfaces the default value is assigned as described in
:ref:`hardware_interfaces_defaults`. Both the hardware type and the hardware
interfaces can be changed later via the node update API.

Changing Hardware Interfaces
~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Hardware interfaces can be changed by the following command::

    openstack baremetal node set <NODE> \
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

    openstack baremetal node create --name test --driver fake-hardware
    openstack baremetal node set test --driver ipmi

This is because the ``fake-hardware`` hardware type defaults to ``fake``
implementations for some or all interfaces, but the ``ipmi`` hardware type is
not compatible with them. There are three ways to deal with this situation:

#. Provide new values for all incompatible interfaces, for example::

    openstack baremetal node set test --driver ipmi \
        --boot-interface pxe \
        --deploy-interface iscsi \
        --management-interface ipmitool \
        --power-interface ipmitool

#. Request resetting some of the interfaces to their new defaults by using the
   ``--reset-<IFACE>-interface`` family of arguments, for example::

    openstack baremetal node set test --driver ipmi \
        --reset-boot-interface \
        --reset-deploy-interface \
        --reset-management-interface \
        --reset-power-interface

   .. note:: This feature is available starting with ironic 11.1.0 (Rocky
             series, API version 1.45).

#. Request resetting all interfaces to their new defaults::

    openstack baremetal node set test --driver ipmi --reset-interfaces

   You can still specify explicit values for some interfaces::

    openstack baremetal node set test --driver ipmi --reset-interfaces \
        --deploy-interface direct

   .. note:: This feature is available starting with ironic 11.1.0 (Rocky
             series, API version 1.45).

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
