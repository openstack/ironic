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

  drivers/cimc
  drivers/idrac
  drivers/ilo
  drivers/ipmitool
  drivers/irmc
  drivers/oneview
  drivers/redfish
  drivers/snmp
  drivers/ucs


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
.. _VirtualBMC: https://git.openstack.org/cgit/openstack/virtualbmc
