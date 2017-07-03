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

- Add ``pxe_snmp`` to the list of ``enabled_drivers`` in
  ``/etc/ironic/ironic.conf``
- Ironic Conductor must be restarted for the new driver to be loaded.

Ironic Node Configuration
=========================

Nodes are configured for SNMP control by setting the Ironic node object's
``driver`` property to be ``pxe_snmp``.  Further configuration values are
added to ``driver_info``:

- ``snmp_driver``: PDU manufacturer driver
- ``snmp_address``: the IPv4 address of the PDU controlling this node.
- ``snmp_port``: (optional) A non-standard UDP port to use for SNMP operations.
  If not specified, the default port (161) is used.
- ``snmp_outlet``: The power outlet on the PDU (1-based indexing).
- ``snmp_protocol``: (optional) SNMP protocol version
  (permitted values ``1``, ``2c`` or ``3``). If not specified, SNMPv1
  is chosen.
- ``snmp_community``: (Required for SNMPv1 and SNMPv2c) SNMP community
  parameter for reads and writes to the PDU.
- ``snmp_security``: (Required for SNMPv3) SNMP security string.

PDU Configuration
=================

This version of the SNMP power driver does not support handling
PDU authentication credentials. When using SNMPv3, the PDU must be
configured for ``NoAuthentication`` and ``NoEncryption``. The
security name is used analogously to the SNMP community in early
SNMP versions.
