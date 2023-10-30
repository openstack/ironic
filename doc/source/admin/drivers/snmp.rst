===========
SNMP driver
===========

The SNMP hardware type enables control of power distribution units of the type
frequently found in data centre racks. PDUs frequently have a management
ethernet interface and SNMP support enabling control of the power outlets.

The SNMP power interface works with the :ref:`pxe-boot` interface for network
deployment and network-configured boot.

.. note::
    Unlike most of the other power interfaces, the SNMP power interface does
    not have a corresponding management interface. The SNMP hardware type uses
    the ``noop`` management interface instead.

List of supported devices
=========================

This is a non-exhaustive list of supported devices. Any device not listed in
this table could possibly work using a similar driver.

Please report any device status.

==============   ==============   ==========   =====================
Manufacturer     Model            Supported?   Driver name
==============   ==============   ==========   =====================
APC              AP7920           Yes          apc_masterswitch
APC              AP9606           Yes          apc_masterswitch
APC              AP9225           Yes          apc_masterswitchplus
APC              AP7155           Yes          apc_rackpdu
APC              AP7900           Yes          apc_rackpdu
APC              AP7901           Yes          apc_rackpdu
APC              AP7902           Yes          apc_rackpdu
APC              AP7911a          Yes          apc_rackpdu
APC              AP7921           Yes          apc_rackpdu
APC              AP7922           Yes          apc_rackpdu
APC              AP7930           Yes          apc_rackpdu
APC              AP7931           Yes          apc_rackpdu
APC              AP7932           Yes          apc_rackpdu
APC              AP7940           Yes          apc_rackpdu
APC              AP7941           Yes          apc_rackpdu
APC              AP7951           Yes          apc_rackpdu
APC              AP7960           Yes          apc_rackpdu
APC              AP7990           Yes          apc_rackpdu
APC              AP7998           Yes          apc_rackpdu
APC              AP8941           Yes          apc_rackpdu
APC              AP8953           Yes          apc_rackpdu
APC              AP8959           Yes          apc_rackpdu
APC              AP8961           Yes          apc_rackpdu
APC              AP8965           Yes          apc_rackpdu
Aten             all?             Yes          aten
CyberPower       all?             Untested     cyberpower
EatonPower       all?             Untested     eatonpower
Teltronix        all?             Yes          teltronix
BayTech          MRP27            Yes          baytech_mrp27
Raritan          PX3-5547V-V2     Yes          raritan_pdu2
Raritan          PX3-5726V        Yes          raritan_pdu2
Raritan          PX3-5776U-N2     Yes          raritan_pdu2
Raritan          PX3-5969U-V2     Yes          raritan_pdu2
Raritan          PX3-5961I2U-V2   Yes          raritan_pdu2
Vertiv           NU30212          Yes          vertivgeist_pdu
ServerTech       CW-16VE-P32M     Yes          servertech_sentry3
ServerTech       C2WG24SN         Yes          servertech_sentry4
==============   ==============   ==========   =====================


Software Requirements
=====================

Additional python libraries to communicate with SNMP are required. Please see
``driver-requirements.txt`` for an updated list for your release.

Enabling the SNMP Hardware Type
===============================

#. Add ``snmp`` to the list of ``enabled_hardware_types`` in ``ironic.conf``.
   Also update ``enabled_management_interfaces`` and
   ``enabled_power_interfaces`` in ``ironic.conf`` as shown below:

   .. code-block:: ini

    [DEFAULT]
    enabled_hardware_types = snmp
    enabled_management_interfaces = noop
    enabled_power_interfaces = snmp

#. To enable the network boot fallback, update ``enable_netboot_fallback`` in
   ``ironic.conf``:

   .. code-block:: ini

    [pxe]
    enable_netboot_fallback = True

   .. note::
      It is important to enable the fallback as SNMP hardware type does not
      support setting of boot devices. When booting in legacy (BIOS) mode,
      the generated network booting artifact will force booting from local
      disk. In UEFI mode, Ironic will configure the boot order using UEFI
      variables.

#. Restart the Ironic conductor service.

   .. code-block:: bash

    service ironic-conductor restart

Ironic Node Configuration
=========================

Nodes configured to use the SNMP hardware type should have the ``driver`` field
set to the hardware type ``snmp``.

The following property values have to be added to the node's
``driver_info`` field:

- ``snmp_driver``: PDU manufacturer driver name or ``auto`` to automatically
  choose ironic snmp driver based on ``SNMPv2-MIB::sysObjectID`` value as
  reported by PDU.
- ``snmp_address``: the IPv4 address of the PDU controlling this node.
- ``snmp_port``: (optional) A non-standard UDP port to use for SNMP operations.
  If not specified, the default port (161) is used.
- ``snmp_outlet``: The power outlet on the PDU (1-based indexing).
- ``snmp_version``: (optional) SNMP protocol version
  (permitted values ``1``, ``2c`` or ``3``). If not specified, SNMPv1
  is chosen.
- ``snmp_community``: (Required for SNMPv1/SNMPv2c unless
  ``snmp_community_read`` and/or ``snmp_community_write`` properties are
  present in which case the latter take over) SNMP community
  name parameter for reads and writes to the PDU.
- ``snmp_community_read``: SNMP community name parameter for reads
  to the PDU. Takes precedence over the ``snmp_community`` property.
- ``snmp_community_write``: SNMP community name parameter for writes
  to the PDU. Takes precedence over the ``snmp_community`` property.
- ``snmp_user``: (Required for SNMPv3) SNMPv3 User-based Security Model
  (USM) user name. Synonym for now obsolete ``snmp_security`` parameter.
- ``snmp_auth_protocol``: SNMPv3 message authentication protocol ID.
  Valid values include: ``none``, ``md5``, ``sha`` for all pysnmp versions
  and additionally ``sha224``, ``sha256``, ``sha384``, ``sha512`` for
  pysnmp versions 4.4.1 and later. Default is ``none`` unless ``snmp_auth_key``
  is provided. In the latter case ``md5`` is the default.
- ``snmp_auth_key``: SNMPv3 message authentication key. Must be 8+
  characters long. Required when message authentication is used.
- ``snmp_priv_protocol``: SNMPv3 message privacy (encryption) protocol ID.
  Valid values include: ``none``, ``des``, ``3des``, ``aes``, ``aes192``,
  ``aes256`` for all pysnmp version and additionally ``aes192blmt``,
  ``aes256blmt`` for pysnmp versions 4.4.3+. Note that message privacy
  requires using message authentication. Default is ``none`` unless
  ``snmp_priv_key`` is provided. In the latter case ``des`` is the default.
- ``snmp_priv_key``:  SNMPv3 message privacy (encryption) key. Must be 8+
  characters long. Required when message encryption is used.
- ``snmp_context_engine_id``: SNMPv3 context engine ID. Default is
  the value of authoritative engine ID.
- ``snmp_context_name``: SNMPv3 context name. Default is an empty string.

The following command can be used to enroll a node with the ``snmp`` hardware
type:

.. code-block:: bash

    baremetal node create \
    --driver snmp --driver-info snmp_driver=<pdu_manufacturer> \
    --driver-info snmp_address=<ip_address> \
    --driver-info snmp_outlet=<outlet_index> \
    --driver-info snmp_community=<community_string>
