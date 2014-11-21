.. _drivers:

=================
Enabling Drivers
=================

DRAC
----

DRAC with PXE deploy
^^^^^^^^^^^^^^^^^^^^

- Add ``pxe_drac`` to the list of ``enabled_drivers in`` ``/etc/ironic/ironic.conf``
- Install openwsman-python package

SNMP
----

The SNMP power driver enables control of power distribution units of the type
frequently found in data centre racks. PDUs frequently have a management
ethernet interface and SNMP support enabling control of the power outlets.

The SNMP power driver works with the PXE driver for network deployment and
network-configured boot.

Supported PDUs
^^^^^^^^^^^^^^

- American Power Conversion (APC)
- CyberPower (implemented according to MIB spec but not tested on hardware)
- EatonPower (implemented according to MIB spec but not tested on hardware)
- Teltronix

Software Requirements
^^^^^^^^^^^^^^^^^^^^^

- The PySNMP package must be installed, variously referred to as ``pysnmp``
  or ``python-pysnmp``

Enabling the SNMP Power Driver
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

- Add ``pxe_snmp`` to the list of ``enabled_drivers`` in ``/etc/ironic/ironic.conf``
- Ironic Conductor must be restarted for the new driver to be loaded.

Ironic Node Configuration
^^^^^^^^^^^^^^^^^^^^^^^^^

Nodes are configured for SNMP control by setting the Ironic node object's
``driver`` property to be ``pxe_snmp``.  Further configuration values are
added to ``driver_info``:

- ``snmp_address``: the IPv4 address of the PDU controlling this node.
- ``snmp_port``: (optional) A non-standard UDP port to use for SNMP operations.
  If not specified, the default port (161) is used.
- ``snmp_outlet``: The power outlet on the PDU (1-based indexing).
- ``snmp_protocol``: (optional) SNMP protocol version
  (permitted values ``1``, ``2c`` or ``3``). If not specified, SNMPv1 is chosen.
- ``snmp_community``: (Required for SNMPv1 and SNMPv2c) SNMP community
  parameter for reads and writes to the PDU.
- ``snmp_security``: (Required for SNMPv3) SNMP security string.

PDU Configuration
^^^^^^^^^^^^^^^^^

This version of the SNMP power driver does not support handling
PDU authentication credentials. When using SNMPv3, the PDU must be
configured for ``NoAuthentication`` and ``NoEncryption``. The
security name is used analagously to the SNMP community in early
SNMP versions.

iLO driver
----------

.. toctree::
  :maxdepth: 1

  ../drivers/ilo

SeaMicro driver
---------------

.. toctree::
  :maxdepth: 1

  ../drivers/seamicro
