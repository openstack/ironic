Configuring services for bare metal provisioning using IPv6
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Use of IPv6 addressing for baremetal provisioning requires additional
configuration. This page covers the IPv6 specifics only. Please refer to
:doc:`/install/configure-tenant-networks` and
:doc:`/install/configure-networking` for general networking configuration.


Configure ironic PXE driver for provisioning using IPv6 addressing
==================================================================

The ironic PXE driver operates in either IPv4 or IPv6 mode (IPv4 is the
default). To enable IPv6 mode, set the ``[pxe]/ip_version`` option in the Bare
Metal Service's configuration file (``/etc/ironic/ironic.conf``) to ``6``.

.. Note:: Support for dual mode IPv4 and IPv6 operations is planned for a
          future version of ironic.


Provisioning with IPv6 stateless addressing
-------------------------------------------

When using stateless addressing DHCPv6 does not provide addresses to the client.
DHCPv6 however provides other configuration via DHCPv6 options such as the
bootfile-url and bootfile-parameters.

Once the PXE driver is set to operate in IPv6 mode no further configuration is
required in the Baremetal Service.

Creating networks and subnets in the Networking Service
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

When creating the Baremetal Service network(s) and subnet(s) in the Networking
Service's, subnets should have ``ipv6-address-mode`` set to ``dhcpv6-stateless``
and ``ip-version`` set to ``6``. Depending on whether a router in the Networking
Service is providing RA's (Router Advertisements) or not, the ``ipv6-ra-mode``
for the subnet(s) should either be set to ``dhcpv6-stateless`` or be left unset.

.. Note:: If ``ipv6-ra-mode`` is left unset, an external router on the network
          is expected to provide RA's with the appropriate flags set for
          automatic addressing and other configuration.


Provisioning with IPv6 stateful addressing
------------------------------------------

When using stateful addressing DHCPv6 is providing both addresses and other
configuration via DHCPv6 options such as the bootfile-url and bootfile-
parameters.

The "identity-association" (IA) construct used by DHCPv6 is challenging when
booting over the network. Firmware, and ramdisks typically end up using
different DUID/IAID combinations and it is not always possible for one chain-
booting stage to release its address before giving control to the next step. In
case the DHCPv6 server is configured with static reservations only the result is
that booting will fail because the DHCPv6 server has no addresses available. To
get past this issue either configure the DHCPv6 server with multiple address
reservations for each host, or use a dynamic range.

.. Note:: Support for multiple address reservations requires dnsmasq version
          2.81 or later. Some distributions may backport this feature to
          earlier dnsmasq version as part of the packaging, check the
          distributions release notes.

          If a different (not dnsmasq) DHCPv6 server backend is used with the
          Networking service, use of multiple address reservations might not
          work.

Using the ``flat`` network interface
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

Due to the "identity-association" challenges with DHCPv6 provisioning using the
``flat`` network interface is not recommended. When ironic operates with the
``flat`` network interface the server instance port is used for provisioning and
other operations. Ironic will not use multiple address reservations in this
scenario. Because of this **it will not work in most cases**.

Using the ``neutron`` network interface
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

When using the ``neutron`` network interface the Baremetal Service will allocate
multiple IPv6 addresses (4 addresses per port by default) on the service
networks used for provisioning, cleaning, rescue and introspection. The number
of addresses allocated can be controlled via the
``[neutron]/dhcpv6_stateful_address_count`` option in the Bare Metal Service's
configuration file (``/etc/ironic/ironic.conf``). Using multiple address
reservations ensures that the DHCPv6 server can lease addresses to each step.

To enable IPv6 provisioning on neutron *flat* provider networks with no switch
management, the ``local_link_connection`` field of baremetal ports must be set
to ``{'network_type': 'unmanaged'}``. The following example shows how to set the
local_link_connection for operation on unmanaged networks::

  openstack baremetal port set \
    --local-link-connection network_type=unmanaged <port-uuid>

The use of multiple IPv6 addresses must also be enabled in the Networking
Service's dhcp agent configuration (``/etc/neutron/dhcp_agent.ini``) by setting
the option ``[DEFAULT]/dnsmasq_enable_addr6_list`` to ``True`` (default
``False`` in Ussuri release).

.. Note:: Support for multiple IPv6 address reservations in the dnsmasq backend
          was added to the Networking Service Ussuri release. It was also
          backported to the stable Train release.


Creating networks and subnets in the Networking Service
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

When creating the ironic service network(s) and subnet(s) in the Networking
Service, subnets should have ``ipv6-address-mode`` set to ``dhcpv6-stateful``
and ``ip-version`` set to ``6``. Depending on whether a router in the Networking
Service is providing RA's (Router Advertisements) or not, the ``ipv6-ra-mode``
for the subnet(s) should be set to either ``dhcpv6-stateful`` or be left
unset.

.. Note:: If ``ipv6-ra-mode`` is left unset, an external router on the network
          is expected to provide RA's with the appropriate flags set for managed
          addressing and other configuration.
