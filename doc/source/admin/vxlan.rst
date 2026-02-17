================
VXLAN Networking
================

Overview
========

During the 2025.1 (Gazpacho) development cycle, the Ironic community merged
initial support for using VXLAN networks with bare metal workloads. This
capability enables bare metal hosts to attach to VXLAN tenant networks in the
same way virtual machines do, while leveraging the physical network switch
fabric to perform VXLAN termination and translation.

This document describes the architecture, requirements, and operational
considerations for deploying VXLAN networking with Ironic.

What is VXLAN Support for Bare Metal?
======================================

This functionality enables bare metal nodes to participate in VXLAN overlay
networks without acting as VXLAN Tunnel Endpoints (VTEPs) themselves. Instead,
the physical network switches act as VTEPs, terminating VXLAN tunnels and
translating them to VLANs on the physical switch ports where bare metal nodes
are connected.

From the bare metal host's perspective, it receives untagged Ethernet traffic
on its network interface. However, this traffic is mapped to a VXLAN Network
Identifier (VNI) within the network fabric, allowing it to share a logical
network with virtual machines using VXLAN overlay networking.

.. note::
   This implementation also supports Geneve network types in the same manner
   as VXLAN, translating them to VLAN attachments at the physical switch
   level. Such a configuration has received some basic testing in development
   as OVN treats the packets no differently than networks configured as VXLAN.

Why VXLAN Networking?
=====================

Network operators face several challenges that VXLAN addresses:

**VLAN Limitations**
   Traditional VLAN-based networking is constrained by the 4,096 VLAN limit
   (12-bit VLAN ID). In large-scale deployments, this constraint can become a
   significant limitation, especially when isolating tenant networks. VXLAN
   provides a 24-bit VNI space, supporting up to 16 million network segments.

**Network Scalability**
   VXLAN enables routed spine-leaf network architectures where overlay traffic
   can traverse Layer 3 boundaries. This eliminates the need for spanning
   tree protocols across large fabrics and enables more efficient traffic
   patterns.

**Workload Integration**
   In clouds running both virtual machines and bare metal nodes, VXLAN support
   enables seamless network integration. Tenant networks can span both
   virtualized and bare metal resources without requiring separate network
   infrastructure or administrative network creation.

**Simplified Tenant Experience**
   Unlike traditional VLAN networking in Ironic, which requires administrative
   privileges to create tenant networks (due to the need to specify physical
   network mappings), VXLAN networks can be created by regular users when
   the default tenant network type is configured for VXLAN or Geneve.

Terminology
===========

VXLAN (Virtual eXtensible LAN)
   An overlay network protocol that encapsulates Layer 2 Ethernet frames
   within Layer 4 UDP packets, enabling Layer 2 networks to span Layer 3
   boundaries.

VXLAN Network Identifier (VNI)
   A 24-bit identifier that uniquely identifies a VXLAN segment. Similar to
   a VLAN ID but with a much larger address space (16 million vs 4,096).

VXLAN Tunnel Endpoint (VTEP)
   A device (switch or host) that originates and/or terminates VXLAN tunnels,
   performing encapsulation and decapsulation of Ethernet frames.

Hierarchical Port Binding
   A Neutron mechanism that creates multiple binding segments for a single
   port. In this context, a "top" segment represents the VXLAN network and
   a "bottom" segment represents the physical VLAN used on the switch.

Lower Binding Segment
   The physical VLAN segment allocated by Neutron as part of hierarchical
   port binding. This VLAN is used internally by the switch fabric to map
   to the VXLAN VNI.

BGP EVPN (Ethernet VPN)
   A control plane protocol using BGP to distribute MAC address reachability
   information across a VXLAN fabric. This enables efficient forwarding and
   reduces broadcast, unknown unicast, and multicast (BUM) traffic.

Ingress Replication
   A method of handling broadcast, unknown unicast, and multicast traffic in
   VXLAN where the source VTEP replicates packets to each remote VTEP that
   is part of the VNI.

Architecture
============

The VXLAN support for Ironic consists of three main components:

1. **Mechanism Driver (baremetal-l2vni)**
   Handles hierarchical port binding for VXLAN and Geneve network types,
   allocating lower binding segments (VLANs) from the physical network pool.
   This driver also creates OVN "localnet" ports to bridge the logical
   overlay network to the physical network infrastructure.

2. **Physical Network Connectivity**
   Establishes the connection between the OpenStack cloud (specifically OVN
   network nodes) and the physical switch fabric. This can be implemented
   through hierarchical port binding with trunk ports, or through BGP EVPN
   Type-2 routes (under development in Neutron and should be expected as a
   result of the Hibiscus development cycle).

   .. NOTE::
      The future integration of Neutron BGP EVPN Type-2 routes may not
      work for network types set to Geneve. Ultimately it works in the case
      where the baremetal-l2vni plugin creates a direct "localnet" port
      attachment, because internally OVN treats the packets with no
      difference as they traverse OVN itself. The Ironic project expects
      to test that integration once available and when time permits and
      is expected to then update documentation accordingly.

3. **Switch Configuration Driver**
   Programs the physical switches to create VNI-to-VLAN mappings and attach
   VLANs to physical ports. The networking-generic-switch ML2 plugin provides
   this functionality for common switch vendors. Third party ML2 plugins can
   be extended to support such a functionality by their maintainers.

Data Flow
---------

The following diagram illustrates the packet flow for VXLAN bare metal
networking::

    ┌─────────────────┐              ┌──────────────┐
    │ Bare Metal Host │              │ Virtual      │
    │  (untagged)     │              │ Machine      │
    └────────┬────────┘              └──────┬───────┘
             │                              │
             │ Untagged Ethernet            │ OVN Port to VXLAN VNI 2000
             │                              │
    ┌────────▼──────────┐           ┌───────▼────────┐
    │ Switch Port       │           │ Hypervisor     │
    │ VLAN 100          │           │ (OVN)          │
    └────────┬──────────┘           └───────┬────────┘
             │                              │
             │ VLAN 100 → VNI 2000          │
             │ (switch acts as VTEP)        │ OVN Flow for VNI 2000
             │                              │
    ┌────────▼──────────────────────────────▼────────┐
    │          Network Fabric (Layer 3)              │
    │          VXLAN VNI 2000 routed traffic         │
    └────────┬───────────────────────────────────────┘
             │
    ┌────────▼───────────┐
    │ OVN Network Node   │
    │ br-ex VLAN tag 100 │ ← VLAN 100 subinterface
    │    ↓               │
    │ localnet port      │ → Bridges to OVN logical network
    │    ↓               │
    │ OVN Network        │
    │ VNI 2000           │
    └────────────────────┘

The traffic flow works as follows:

1. Bare metal host sends untagged Ethernet frames
2. Physical switch tags frames with VLAN ID (e.g., VLAN 100)
3. Switch maps VLAN 100 to VXLAN VNI 2000 and encapsulates
4. VXLAN traffic is routed through the network fabric
5. Remote switches and OVN network nodes with the same VNI mapping receive
   the traffic
6. OVN network node receives VLAN 100 on br-ex trunk port, which is mapped
   to an OVN localnet port in the OVN logical network
7. Virtual machines on the same OVN network can communicate directly through
   the overlay network.

.. NOTE::
   In the diagram above, an OVN Network Node is being used. It is entirely
   possible to utilize hypervisors as well and perform some level of direct
   attachment. Such configurations are entirely dependent upon the operator
   applied configuration to OVN itself and all flows would exist within the
   constraints of OVN.

.. NOTE::
   When a tenant network is configured to be a ``vxlan`` network in an OVN
   enabled Neutron deployment, OVN does not utilize ``vxlan`` to transport
   the packets to the hypervisor. The packets are sent directly to the
   hypervisor over fabric which OVN orchestrates with additional header
   information which is VXLAN incompatible.

OVN Integration
---------------

In an OVN-based deployment, the mechanism driver creates "localnet" ports in
the OVN logical network. These ports represent attachments to physical
networks and are mapped to specific bridge mappings on OVN chassis nodes.

The OVN controller manages the lifecycle of these localnet ports, enabling
them on nodes that have appropriate bridge mappings and disabling them when
network topology changes. This provides automatic failover and load
distribution across multiple network nodes.

Requirements
============

To deploy VXLAN networking for bare metal, the following components and
configuration are required:

Infrastructure Requirements
---------------------------

- **VXLAN-capable physical switches**
  Your switch fabric must support VXLAN. Ingress replication is the
  recommended configuration and first targeted support case. Additional
  models of VXLAN traffic management within a VXLAN network are expected
  to evolve in the networking-generic-switch ML2 plugin as this feature
  set gets more adoption.

- **Neutron with OVN**
  The implementation uses OVN as the network virtualization platform.
  Other options are not presently supported.

- **Network nodes with physical connectivity**
  One or more network nodes (dedicated or compute nodes) with physical
  network interfaces connected to the switch fabric with matching
  ``physical_network`` network names.

Software Components
-------------------

The following Neutron ML2 plugins must be installed and configured:

1. **networking-baremetal**
   Provides the ``baremetal-l2vni`` mechanism driver.

2. **networking-generic-switch** (or alternative switch ML2 plugin)
   Programs physical switches with VXLAN VNI and VLAN configuration.

Configuration Requirements
--------------------------

Mechanism Driver Ordering
~~~~~~~~~~~~~~~~~~~~~~~~~

In ``/etc/neutron/plugins/ml2/ml2_conf.ini``, the mechanism drivers must be
configured in the correct order::

    [ml2]
    mechanism_drivers = ovn,baremetal-l2vni,genericswitch,baremetal

The ``baremetal-l2vni`` driver must appear:

- After ``ovn`` (to ensure OVN processes the port binding first)
- Before ``baremetal`` (to create the hierarchical binding)
- Before the switch configuration driver (e.g., ``genericswitch``)

Physical Network Configuration
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Each bare metal port must be associated with a physical network. This can be
configured either:

1. **Per-port** using the ``physical_network`` attribute::

       openstack baremetal port set --physical-network physnet1 <port-uuid>

2. **Default** in ``/etc/neutron/plugins/ml2/ml2_conf.ini``::

       [l2vni]
       default_physical_network = physnet1

The physical network must have VLAN segments allocated. The mechanism driver
will allocate VLANs from this pool as lower binding segments for VXLAN
networks.

.. warning::
   Physical network names and VLAN ranges must be consistently configured
   across all Neutron services. Inconsistent configuration will result in
   port binding failures.

Network Type Configuration
~~~~~~~~~~~~~~~~~~~~~~~~~~

For users to create VXLAN networks without administrative privileges, set
the tenant network type::

    [ml2]
    project_network_types = vxlan

    [ml2_type_vxlan]
    vni_ranges = 5000:10000

.. note::
   The ``project_network_types`` parameter can be set to ``geneve``,
   which is the default value for the setting. This is known to work for
   the ``baremetal-l2vni`` model of using ``localnet`` ports.

.. warning::
   Provider networks (networks created with ``--provider-*`` options) are
   not supported with this model.

Physical Switch Configuration
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Switches must be configured with:

- VXLAN support enabled
- BGP EVPN or multicast configuration for control plane to enable a VNI
  to be configured and the traffic to reach from one VTEP to another on
  the same network.
- Ingress replication configured (recommended)
- Appropriate interface addresses for VTEP functionality

The specific configuration varies by vendor and is typically done through
the switch management interface or automation tools.

Connectivity Models
===================

There are two primary models for connecting the OpenStack cloud to the
physical switch fabric for VXLAN traffic.

Option 1: Hierarchical Port Binding with Trunk Ports
-----------------------------------------------------

This is the currently implemented and recommended approach for most
deployments.

In this model:

- Each OVN network node has one or more physical network interfaces
  connected to the switch fabric
- These interfaces are configured as 802.1Q trunk ports in Neutron
- For each VXLAN network that needs physical connectivity, a VLAN subport
  is created on the trunk
- The VLAN ID matches the lower binding segment allocated by the mechanism
  driver
- The physical switch maps the VLAN to the VXLAN VNI

**Advantages:**

- Leverages switch ASICs for VXLAN encapsulation/decapsulation, providing
  near wire-speed performance
- Proven approach already in use by downstream operators
- Straightforward configuration and troubleshooting

**Limitations:**

- Number of networks is limited by available VLANs per physical network
  (typically 4,096, but often lower due to switch constraints)
- May require careful planning of physical network assignments to avoid
  VLAN exhaustion
- Adds latency for VM-to-baremetal traffic as packets must traverse to
  network nodes

**Best For:**

- Bare metal-heavy deployments
- Environments requiring high bandwidth between bare metal nodes as
  traffic does not bridge across Network Nodes.
- Use cases where switch performance is critical

Option 2: BGP EVPN with Type-2 Routes
--------------------------------------

This approach is under development in the Neutron community and represents
a future connectivity model.

In this model:

- Each compute node participates in BGP EVPN as a VTEP
- MAC address routes are distributed via BGP Type-2 routes
- VXLAN encapsulation/decapsulation occurs on hypervisors
- Physical switches also participate in the EVPN fabric

**Advantages:**

- Distributed encapsulation/decapsulation across compute nodes
- No VLAN constraints on network nodes
- Better scaling for VM-heavy environments

**Limitations:**

- CPU overhead on hypervisors for packet encapsulation/decapsulation
- Lower per-stream performance compared to switch ASICs
- More complex BGP configuration required

**Best For:**

- VM-heavy deployments with some bare metal nodes
- Environments prioritizing horizontal scalability
- Use cases where distributed processing is preferred

Choosing a Connectivity Model
------------------------------

The choice between connectivity models depends on your workload
characteristics:

**Use Hierarchical Port Binding if:**

- Most traffic is between bare metal nodes
- You need maximum bandwidth and lowest latency
- Your switch fabric is designed for VXLAN/EVPN
- VLAN limits per physical network are acceptable
- Your Traffic flow performance is critical.

**Use BGP EVPN (when available) if:**

- Most traffic is between VMs with occasional bare metal communication
- You want to distribute encapsulation load across compute nodes
- VLAN constraints are problematic
- Your deployment is VM-centric with bare metal as a secondary workload

.. NOTE::
   The physical network modeling in OpenStack has historically represented
   entirely different broadcast or management domains. But ultimately they
   are a human management construct where a single node **can** have multiple
   physical networks, and it is just configuration to allow operators to model
   how they would prefer traffic to flow and define the overall structural
   bounds of a network.

Supported Switch Vendors
=========================

The networking-generic-switch plugin provides VXLAN support for the
following switch operating systems:

- **Cisco Nexus** (NX-OS)
- **Arista EOS**
- **Juniper Junos**
- **SONiC** (vendor-neutral network OS)
- **Cumulus Networks NVUE**

.. note::
   Additional switch vendors may be supported through third-party ML2
   plugins. Check your switch vendor's documentation for OpenStack
   integration options.

Unsupported Switch Platforms
-----------------------------

**Dell OS10**
   While Dell OS10 supports VXLAN, it uses a three-tier mapping system
   (VLAN → Virtual Network → VNI) that requires a 16-bit virtual network ID
   in addition to the VLAN and VNI. This architecture cannot be easily
   automated with the current hierarchical port binding model and is
   therefore not supported. Furthermore, there are recommended limits to
   the number of VLAN on any given trunk interface which operators would
   need to be mindful of.

Switch Configuration Details
----------------------------

Each switch vendor requires specific configuration parameters. Common
requirements include:

- **BGP ASN** - Autonomous System Number for BGP EVPN
- **VTEP interface** - Loopback or interface address used as the VXLAN
  source
- **Route distinguisher/target** - BGP EVPN routing parameters

Consult the networking-generic-switch documentation and your switch vendor's
VXLAN/EVPN configuration guides for specific parameters.

Operational Procedures
======================

Creating Networks
-----------------

With VXLAN support properly configured, regular (non-admin) users can create
networks::

    openstack network create my-network

The network will automatically:

1. Be assigned a VNI from the configured range
2. Have lower binding segments (VLANs) allocated per physical network
3. Be ready for bare metal and VM attachments

Attaching Bare Metal Nodes
---------------------------

1. Ensure the bare metal port has a ``physical_network`` set::

       openstack baremetal port set --physical-network physnet1 <port-uuid>

2. Create a port on the VXLAN network::

       openstack port create --network my-network bare-port

3. Attach the port to a bare metal node::

       openstack baremetal node vif attach <node> <port-uuid>

The mechanism driver will:

- Allocate a VLAN from the physical network if not already allocated
- Program the physical switch to create the VNI and map it to the VLAN
- Attach the VLAN to the physical switch port

Monitoring Network Segments
----------------------------

View the hierarchical binding segments for a network::

    openstack network segment list --network my-network

You should see at least two segments:

- **Top segment**: network_type ``vxlan`` or ``geneve`` with the VNI
- **Bottom segment(s)**: network_type ``vlan`` with VLAN IDs per physical
  network

Troubleshooting
===============

Port Binding Failures
---------------------
**Symptom**: Baremetal node transitions from ``deploying`` to ``deploy fail``
and back to ``available`` due to the Neutron port binding failing.

**Alternative Symptom**: Bare metal node is stuck in "wait call-back" or "deploying"
state for a period of time before going to "deploy fail" state and
transitioning back to available.

Largely this pattern of behavior will be governed by the
setting of :oslo.config:option:`neutron.fail_on_port_binding_failure`,
where the default value will represent the pattern observed in the first
symptom, and the latter symptoms will represent the behavior when set to
False.

Ultimately, this is due to one of the common causes noted below.

**Common Causes**:

1. **No physical_network configured**

   Check if the port has a physical_network::

       openstack baremetal port show <port-uuid> -c physical_network

   Set if missing::

       openstack baremetal port set --physical-network physnet1 <port-uuid>

.. NOTE::
   Networking-baremetal has a configuration option which can be placed into
   the "[baremetal_l2vni]" section of the Neutron ml2.conf files named
   ``default_physical_network`` which can be used in smaller scale cases
   where a physical network is not found on physical ports.

2. **VLAN exhaustion on physical network**

   Check available VLANs in ``/etc/neutron/plugins/ml2/ml2_conf.ini``::

       [ml2_type_vlan]
       network_vlan_ranges = physnet1:100:200

   If the range is exhausted, either:

   - Expand the VLAN range (requires verification that the range can be expanded on the physical switch network.)
   - Delete unused networks to free VLANs
   - Use a different physical network. Physical networks are abstract in
     concept and can also co-exist, but must not overlap when it comes to
     the VLAN ranges allocated when they are not completely distinct
     physical networks.

.. NOTE::
   The Ironic project advises over-allocating the number of VLANs to be
   reserved for connecting workloads, as the effort to expand the range
   may seem trivial in configuration, but will require checking that the
   range is actually available on the switch which may yield additional
   unplanned work to make the new desired range available.

3. **Mechanism driver ordering incorrect**

   Verify the mechanism_drivers order in ``ml2_conf.ini``, such that
   the baremetal-l2vni driver is *before* the switch ML2 driver managing
   switchports. Furthermore, generally "baremetal" should be last in the
   list of ports.::

       [ml2]
       mechanism_drivers = ovn,baremetal-l2vni,genericswitch,baremetal

4. **Physical network not configured consistently**

   Ensure the physical network name and VLAN ranges match across all
   Neutron configuration files on all nodes. A miss-matched configuration
   across Neutron nodes can result in configuration and available segments
   behaving unpredictably.

   Ideally, the physical network mapping and range data needs to be consistent
   across all neutron nodes with the exception of the actual bridge mapping
   data for OVN itself. That can be varied as required across a
   deployment to meet the needs of the cloud infrastructure.

Missing Lower Binding Segment
------------------------------

**Symptom**: Network segment list shows only the top VXLAN segment, no
bottom VLAN segment.

**Diagnosis**:

Check the Neutron server logs for errors related to segment allocation::

    sudo journalctl -u neutron-api.service | grep -i segment

.. NOTE:: The service name may differ based upon distribution or
   packages, but generally neutron lots all such issues in the API
   service log.

**Possible Causes**:

- baremetal-l2vni driver not loaded or misconfigured
- No ports have been created on the network yet (lower segments are
  allocated lazily when first port is created)
- Physical network not defined in ml2_conf.ini or on the physical
  ports of baremetal nodes.

Switch Configuration Errors
----------------------------

**Symptom**: Lower segment exists but node cannot communicate on network.

**Diagnosis**:

1. Check switch logs for configuration errors
2. Verify VNI was created on the switch
3. Verify VLAN-to-VNI mapping
4. Check that VLAN is assigned to the correct physical ports
5. Check that OVN *IS* forwarding packets or not. OVN will not
   show the "localnet" port as "up", but generally DHCP will
   be functional. You may need to utilize tools like ``tcpdump``
   to verify OVN is properly attached, and that packets are flowing.
6. Check that a *router* is assigned to the OVN network, without a router
   OVN might not be locking the ports to a ``HA_Chassis_Group`` which
   can result in unexpected OVN behavior.

The specific troubleshooting steps vary by switch vendor. Consult the
networking-generic-switch logs and your switch management interface.

Frequently Asked Questions
==========================

Can I use this on a single switch?
-----------------------------------

Yes. You don't need a multi-switch VXLAN fabric to use this functionality.
The hierarchical port binding and VNI-to-VLAN mapping work on a single
switch.

However, using VXLAN on a single switch doesn't provide the primary benefits
of VXLAN (scaling beyond VLAN limits, Layer 3 fabric, etc.). It may still be
useful for testing or as a migration path to a larger VXLAN deployment.

.. warning::
   Allowing all VLANs to traverse your entire network creates a large
   broadcast domain and negates many benefits of VXLAN. Use appropriate
   VLAN pruning on trunk links.

Can I use this for QinQ (nested VLAN) traffic?
-----------------------------------------------

This is not a tested or supported use case. The VXLAN-to-VLAN translation
model assumes standard Ethernet frames. QinQ (802.1ad) support would depend
on switch capabilities and is not guaranteed to work.

How do I verify a lower segment was created?
---------------------------------------------

Use the network segment list command::

    openstack network segment list --network <network>

You should see multiple segments with the same network ID:

- One with ``network_type: vxlan`` or ``geneve``
- One or more with ``network_type: vlan``

What if DHCP doesn't work?
---------------------------

VXLAN networks with DHCP require the DHCP agent to bind to the network. This
should happen automatically when the network is created.

Verify DHCP port exists::

    openstack port list --network <network> --device-owner \
        network:dhcp

If missing, check the DHCP agent logs::

    sudo journalctl -u neutron-dhcp-agent

Alternatively, you may also need to check the OVN port configuration as well
if you are not presently utilizing the neturon-dhcp-agent and are instead
leveraging native DHCP support in OVN.

Can I tune multicast/BUM traffic handling?
-------------------------------------------

The current implementation is designed for ingress replication mode. While
this is configurable on the switches themselves through BGP EVPN settings,
the ML2 plugin does not expose these controls.

As use cases emerge, additional configuration options may be added to
networking-generic-switch to provide vendor-specific tuning. Please feel
free to open a bug in the `networking-generic-switch launchpad
<https://bugs.launchpad.net/networking-generic-switch>`_ if you have
specific requirements or needs.

Can I mix VLAN and VXLAN networks on the same bare metal node?
---------------------------------------------------------------

Yes. A bare metal node can have multiple ports, some attached to traditional
VLAN networks and others to VXLAN networks. Each port is handled
independently during binding.

Known Limitations
=================

VLAN Constraints per Physical Network
--------------------------------------

Each physical network has a limited number of VLANs available (typically
4,096, but often fewer due to switch vendor limits). Since lower binding
segments consume VLANs, the number of unique VXLAN networks accessible per
physical network is bounded by this limit.

**Mitigation**: Define multiple physical networks to distribute VLAN
allocation across different switch fabrics or VLAN ranges.

.. WARNING::
   Operationally, you should avoid mingling VXLAN and VLAN network types
   on larger switch networks because of the overall management overhead
   created in such setups.

Provider Networks Not Supported
--------------------------------

VXLAN networks created with ``--provider-*`` options are not supported in
this model. The hierarchical binding mechanism expects to allocate the lower
segment automatically.

**Mitigation**: Use regular tenant networks with Geneve or VXLAN as the
default network type.

Performance Depends on Connectivity Model
------------------------------------------

The hierarchical port binding model with trunk ports provides excellent
bare metal-to-bare metal performance but introduces a hop through network
nodes for VM-to-bare metal traffic. This may add latency compared to pure
overlay approaches.

**Mitigation**: Size your network node capacity appropriately and use
multiple network nodes with OVN HA chassis groups for load distribution.

Recovery from Hardware Failures
--------------------------------

If a physical switch fails and is replaced, the VNI and VLAN configuration
must be re-applied. Currently, there is no automatic mechanism to re-trigger
port binding after switch replacement, although upstream development is
underway to add such a capability, see
`change 973413 <https://review.opendev.org/c/openstack/ironic/+/973413>`_
for more details.

**Mitigation**: Document your network-to-physical-network mappings and
utilize switch configuration backup utilities.

No OVN Geneve Support for Physical Fabric
------------------------------------------

While this implementation translates OVN Geneve tenant networks to VXLAN
VNIs on physical switches, it does not support native Geneve protocol on the
physical switch fabric (as Geneve is not widely supported by switch vendors).

Additional Resources
====================

Design Specifications
---------------------

- **VXLAN Support Specification**:
  https://review.opendev.org/c/openstack/ironic-specs/+/959401

External Documentation
----------------------

- **VXLAN RFC 7348**: https://datatracker.ietf.org/doc/html/rfc7348
- **OVN Documentation**: https://docs.ovn.org/
- **Neutron OVN Installation**:
  https://docs.openstack.org/neutron/latest/install/ovn/manual_install.html
