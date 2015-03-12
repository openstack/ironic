.. _drivers:

=================
Enabling Drivers
=================

DRAC
----

DRAC with PXE deploy
^^^^^^^^^^^^^^^^^^^^

- Add ``pxe_drac`` to the list of ``enabled_drivers in``
  ``/etc/ironic/ironic.conf``
- Install openwsman-python package

AMT
----

.. toctree::
  :maxdepth: 1

  ../drivers/amt

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

- Add ``pxe_snmp`` to the list of ``enabled_drivers`` in
  ``/etc/ironic/ironic.conf``
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
  (permitted values ``1``, ``2c`` or ``3``). If not specified, SNMPv1
  is chosen.
- ``snmp_community``: (Required for SNMPv1 and SNMPv2c) SNMP community
  parameter for reads and writes to the PDU.
- ``snmp_security``: (Required for SNMPv3) SNMP security string.

PDU Configuration
^^^^^^^^^^^^^^^^^

This version of the SNMP power driver does not support handling
PDU authentication credentials. When using SNMPv3, the PDU must be
configured for ``NoAuthentication`` and ``NoEncryption``. The
security name is used analogously to the SNMP community in early
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

iRMC
----

The iRMC driver enables PXE Deploy to control power via ServerView Common
Command Interface (SCCI).


Software Requirements
^^^^^^^^^^^^^^^^^^^^^

- Install `python-scciclient package <https://pypi.python.org/pypi/python-scciclient>`_

Enabling the iRMC Driver
^^^^^^^^^^^^^^^^^^^^^^^^

- Add ``pxe_irmc`` to the list of ``enabled_drivers in``
  ``/etc/ironic/ironic.conf``
- Ironic Conductor must be restarted for the new driver to be loaded.

Ironic Node Configuration
^^^^^^^^^^^^^^^^^^^^^^^^^

Nodes are configured for iRMC with PXE Deploy by setting the Ironic node
object's ``driver`` property to be ``pxe_irmc``.  Further configuration values
are added to ``driver_info``:

- ``irmc_address``: hostname or IP of iRMC
- ``irmc_username``: username for iRMC with administrator privileges
- ``irmc_password``: password for irmc_username
- ``irmc_port``: port number of iRMC (optional, either 80 or 443. defalut 443)
- ``irmc_auth_method``: authentication method for iRMC (optional, either
  'basic' or 'digest'. default is 'basic')

Supported Platforms
^^^^^^^^^^^^^^^^^^^
This driver supports FUJITSU PRIMERGY BX S4 or RX S8 servers and above.

- PRIMERGY BX920 S4
- PRIMERGY BX924 S4
- PRIMERGY RX300 S8


VirtualBox drivers
------------------

.. toctree::
  :maxdepth: 1

  ../drivers/vbox
