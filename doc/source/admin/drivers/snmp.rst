===========
SNMP driver
===========

The SNMP power driver enables control of power distribution units of the type
frequently found in data centre racks. PDUs frequently have a management
ethernet interface and SNMP support enabling control of the power outlets.

The SNMP power driver works with the PXE driver for network deployment and
network-configured boot.

List of supported devices
=========================

This is a non-exhaustive list of supported devices. Any device not listed in
this table could possibly work using a similar driver.

Please report any device status.

==============   ==========   ==========    =====================
Manufacturer     Model        Supported?    Driver name
==============   ==========   ==========    =====================
APC              AP7920       Yes           apc_masterswitch
APC              AP9606       Yes           apc_masterswitch
APC              AP9225       Yes           apc_masterswitchplus
APC              AP7155       Yes           apc_rackpdu
APC              AP7900       Yes           apc_rackpdu
APC              AP7901       Yes           apc_rackpdu
APC              AP7902       Yes           apc_rackpdu
APC              AP7911a      Yes           apc_rackpdu
APC              AP7921       Yes           apc_rackpdu
APC              AP7922       Yes           apc_rackpdu
APC              AP7930       Yes           apc_rackpdu
APC              AP7931       Yes           apc_rackpdu
APC              AP7932       Yes           apc_rackpdu
APC              AP7940       Yes           apc_rackpdu
APC              AP7941       Yes           apc_rackpdu
APC              AP7951       Yes           apc_rackpdu
APC              AP7960       Yes           apc_rackpdu
APC              AP7990       Yes           apc_rackpdu
APC              AP7998       Yes           apc_rackpdu
APC              AP8941       Yes           apc_rackpdu
APC              AP8953       Yes           apc_rackpdu
APC              AP8959       Yes           apc_rackpdu
APC              AP8961       Yes           apc_rackpdu
APC              AP8965       Yes           apc_rackpdu
Aten             all?         Yes           aten
CyberPower       all?         Untested      cyberpower
EatonPower       all?         Untested      eatonpower
Teltronix        all?         Yes           teltronix
==============   ==========   ==========    =====================


Software Requirements
=====================

- The PySNMP package must be installed, variously referred to as ``pysnmp``
  or ``python-pysnmp``

Enabling the SNMP Power Driver
==============================

#. Add ``snmp`` to the list of ``enabled_hardware_types`` in ``ironic.conf``.
   Also update ``enabled_management_interfaces`` and
   ``enabled_power_interfaces`` in ``ironic.conf`` as shown below:

   .. code-block:: ini

    [DEFAULT]
    enabled_hardware_types = snmp
    enabled_management_interfaces = fake
    enabled_power_interfaces = snmp

#. Alternatively, if you prefer using the classic driver instead of the
   ``snmp`` hardware type, add ``pxe_snmp`` to the list of ``enabled_drivers``
   in ``ironic.conf``:

   .. code-block:: ini

    [DEFAULT]
    enabled_drivers = pxe_snmp

#. To set the default boot option, update ``default_boot_option`` in
   ``ironic.conf``:

   .. code-block:: ini

    [DEFAULT]
    default_boot_option = netboot

   .. note::
      Currently the default value of ``default_boot_option`` is ``netboot``
      but it will be changed to ``local`` in the future. It is recommended
      to set an explicit value for this option.

   .. note::
      It is important to set ``boot_option`` to ``netboot`` as SNMP drivers
      do not support setting of boot devices. One can also configure a node
      to boot using ``netboot`` by setting its ``capabilities`` and updating
      Nova flavor as described below:

      .. code-block:: console

          openstack baremetal node set --property capabilities="boot_option:netboot" <node-uuid>
          openstack flavor set --property "capabilities:boot_option"="netboot" ironic-flavor


#. Restart the Ironic conductor service.

   .. code-block:: bash

    service ironic-conductor restart

Ironic Node Configuration
=========================

Nodes configured to use the SNMP driver should have the ``driver`` field
set to the hardware type ``snmp`` (preferred) or to the classic driver
``pxe_snmp``.

The following property values have to be added to the node's
``driver_info`` field:

- ``snmp_driver``: PDU manufacturer driver
- ``snmp_address``: the IPv4 address of the PDU controlling this node.
- ``snmp_port``: (optional) A non-standard UDP port to use for SNMP operations.
  If not specified, the default port (161) is used.
- ``snmp_outlet``: The power outlet on the PDU (1-based indexing).
- ``snmp_version``: (optional) SNMP protocol version
  (permitted values ``1``, ``2c`` or ``3``). If not specified, SNMPv1
  is chosen.
- ``snmp_community``: (Required for SNMPv1 and SNMPv2c) SNMP community
  parameter for reads and writes to the PDU.
- ``snmp_security``: (Required for SNMPv3) SNMPv3 User-based Security Model
  (USM) user name.

The following command can be used to enroll a node with the ``snmp`` driver:

.. code-block:: bash

  openstack baremetal node create --os-baremetal-api-version=1.31 \
    --driver snmp --driver-info snmp_driver=<pdu_manufacturer> \
    --driver-info snmp_address=<ip_address> \
    --driver-info snmp_outlet=<outlet_index> \
    --driver-info snmp_community=<community_string> \
    --properties capabilities=boot_option:netboot

PDU Configuration
=================

This version of the SNMP power driver does not support SNMPv3 authentication
or encryption features. When using SNMPv3, the SNMPv3 agent at the PDU must
be configured in ``noAuthNoPriv`` mode. Also, the ``snmp_security`` parameter
is used to configure SNMP USM user name to the SNMP manager at the power
driver.  The same USM user name must be configured to the target SNMP agent.
