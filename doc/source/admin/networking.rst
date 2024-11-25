.. _admin-networking:

======================================
Networking with the Bare Metal service
======================================

Overview
========

Ironic contains several different networking use models and is largely built
around an attachment being requested by the user, be it the ``nova-compute``
service on behalf of a Nova user, or directly using the vif attachment
(``openstack baremetal node vif attach`` or ``baremetal node vif attach``
commands).

Ironic manages the requested attachment state of the vif with the Networking
service, and depending on the overall network-interfaces_ chosen, Ironic will
perform additional actions such as attaching the node to an entirely separate
provider network to improve the overall operational security.

The underlying ``network_interface`` chosen, covered in network-interfaces_
has significant power in the overall model and use of Ironic, and operators
should choose accordingly.

Concepts
========

Terminology
-----------

- ``vif`` or ``VIF`` - Virtual Interface which is best described as a Neutron
  port. VIFs are always referred to utilizing the port ID value.

- ``ML2`` - ML2 is a plugin model for Neutron, the Networking service.
  Advanced networking interactions including 3rd party plugins are utilized
  in this model along with some community plugins to achieve various actions.

- ``provisioning network`` - A separate logical network where bare metal nodes
  are deployed to isolate a deploying node from a tenant controlled, deployed
  node.

- ``cleaning network`` - Similar to the ``provisioning network``, but a
  network where machines undergo cleaning operations.

- ``binding profile`` - A set of information sent to Neutron which includes
  the type of port, in Ironic's case this is always ``VNIC_BAREMETAL``,
  a ``host_id`` value matching the baremetal node's UUID, and any additional
  information like the ``local_link_connection`` information we will cover
  later on in this document, which tells an ML2 plugin where the physical
  baremetal port is attached, enabling network switch fabric configuration
  be appropriately updated.

- ``port group`` - A composite set of ports, created utilizing Ironic's API
  to represent LACP or otherwise bonded network interfaces which exist between
  a network fabric and the physical bare metal node.

.. _network-interfaces:

Network interfaces
------------------

Network interface is one of the driver interfaces that manages network
switching for nodes. There are 3 network interfaces available in
the Bare Metal service:

- ``noop`` interface is used for standalone deployments, and does not perform
  any network switching;

- ``flat`` interface places all nodes into a single provider network that is
  pre-configured on the Networking service and physical equipment. Nodes remain
  physically connected to this network during their entire life cycle. The
  supplied VIF attachment record is updated with new DHCP records as needed.
  When using this network interface, the VIF needs to have been created on the
  same network upon which the bare metal node is physically attached.

- ``neutron`` interface provides tenant-defined networking through the
  Networking service, separating tenant networks from each other and from the
  provisioning and cleaning provider networks. Nodes will move between these
  networks during their life cycle. This interface requires Networking service
  support for the switches attached to the baremetal servers so they can be
  programmed. This interface generally requires use of ML2 plugins or other
  Neutron SDN integrations to facilitate the port configuration actions in
  the network fabric.

VIF Attachment flow
-------------------

When creating a VIF, the action occurs against the Neutron Networking Service,
such as by using the ``openstack port create`` command, and then the port UUID
is submitted to Ironic to facilitate a VIF attachment.

.. NOTE::
   Instances created with Nova can have a Neutron port created under a variety
   of different circumstances. It is *highly* recommended, when using Nova,
   to explicitly declare the port(s) as part of your Nova instance creation
   request. When Nova asks Ironic to deploy a node, nova attempts to record
   all VIFs the user requested to be attached into Ironic, and then generate
   user friendly metadata as a result.

When virtual interface (VIF) is requested to be attached to a node via the
Ironic API, the following ordered criteria are used to select a suitable
unattached port or port group:

* Require ports or port groups to not have a physical network or to have a
  physical network that matches one of the VIF's allowed physical networks.
* Prefer ports and port groups that have a physical network to ports and
  port groups that do not have a physical network.
* Prefer port groups to ports, prefer ports with PXE enabled.

.. NOTE::
   This sequence also assumes the overall request was sent to Ironic without
   a user declared port or port group preference in the attachment request.
   Nova integration does not support explicit declaration of which physical
   port to attach a VIF to, which is a constraint model differing from
   virtual machines.

   Users wishing to have explicit declariation of mappings should consider use
   of Ironic directly to manage Bare Metal resources. This is done with the
   use of the ``--port-uuid <port_uuid>`` option with the ``baremetal node vif
   attach`` command.

As all VIFs are requered to be attached to a port group or independent
ports, the maximum number of VIFs is determined by the number of configured
and available ports represented in Ironic, as framed by the suitablity
criteria noted above.

When Ironic goes to attach *any* supplied, selected, or even self-created
VIFs, Ironic explicitly sets the physical port's MAC address for which the
VIF will be bound. If a node is already in an ``ACTIVE`` state, then the
vif attachment is updated with Neutron.

When Ironic goes to unbind the VIF, Ironic makes a request for Neutron to
"reset" the assigned MAC address in order to avoid conflicts with Neutron's
unique hardware MAC address requirement.

Basic Provisioning flow
~~~~~~~~~~~~~~~~~~~~~~~

When provisioning, Ironic will attempt to attach all PXE enabled
ports to the *provisioning network*. A modifier for this behavior is the
``[neutron]add_all_ports`` option.

After provisioning work has been completed, and prior to the node being
moved to the ``ACTIVE`` ``provision_state``, the previously attached ports
are unbound.

In the case of the ``flat`` ``network_interface```, the requested VIF(s)
utilized for all binding configurations in all states.

In the case of the ``neutron`` ``network_interface``, the user requested VIFs
are attached to the Ironic node for the first time, as the time spent in
the *provisioning network* was utilizing VIFs which Ironic created and then
deleted as part of the baremetal node's movement through the state machine.

The same flow and logic applies to *cleaning*, *service*, and *rescue*
workflows.

How are interfaces configured on the deployed machine
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

The general expectation is that the deployed operating system will utilize
DHCP based autoconfiguration to establish the required configuration into
running state for the newly provisioned machine automatically.

We do not suggest nor recommend attempting to utiize a mix of static
configuration and dynamic configuration. That being said, tools like
`Glean <https://opendev.org/opendev/glean>`_ and `cloud-init
<https://github.com/canonical/cloud-init>`_ may be useful to enable
metadata translation to static system configuration in cases where
it is needed.

Local link connection
---------------------

Use of the ``neutron`` network-interfaces_ requires the Bare Metal port
``local_link_connection`` information to be populated for each bare metal port
on a node in ironic. This information is provided to the Networking service's
ML2 driver when a Virtual Interface (VIF) is attached. The ML2 driver uses the
information to plug the specified port to the tenant network.

.. list-table:: ``local_link_connection`` fields
   :header-rows: 1

   * - Field
     - Description
   * - ``switch_id``
     - Required. Identifies a switch and can be a MAC address or an
       OpenFlow-based ``datapath_id``.
   * - ``port_id``
     - Required. Port ID on the switch/Smart NIC, for example, Gig0/1, rep0-0.
   * - ``switch_info``
     - Optional. Used to distinguish different switch models or other
       vendor-specific identifier. Some ML2 plugins may require this
       field.
   * - ``hostname``
     - Required in case of a Smart NIC port.
       Hostname of Smart NIC device.
.. note::
      This isn't applicable to Infiniband ports because the network topology
      is discoverable by the Infiniband Subnet Manager.
      If specified, local_link_connection information will be ignored.
      If port is Smart NIC port then:

        1. ``port_id`` is the representor port name on the Smart NIC.
        2. ``switch_id`` is not mandatory.

.. _multitenancy-physnets:

Physical networks
-----------------

A Bare Metal port may be associated with a physical network using its
``physical_network`` field. The Bare Metal service uses this information when
mapping between virtual ports in the Networking service and physical ports and
port groups in the Bare Metal service.  A port's physical network field is
optional, and if not set then any virtual port may be mapped to that port,
provided that no free Bare Metal port with a suitable physical network
assignment exists.

The physical network of a port group is defined by the physical network of its
constituent ports. The Bare Metal service ensures that all ports in a port
group have the same value in their physical network field.

Configuring and using Network Multi-tenancy
===========================================

See the :ref:`configure-tenant-networks` section in the installation guide for
the Bare Metal service.

Configuring nodes
=================

#. Ensure that your python-ironicclient version and requested API version
   are sufficient for your requirements.

   * Multi-tenancy support was added in API version 1.20, and is supported by
     python-ironicclient version 1.5.0 or higher.

   * Physical network support for ironic ports was added in API version 1.34,
     and is supported by python-ironicclient version 1.15.0 or higher.

   * Smart NIC support for ironic ports was added in API version 1.53,
     and is supported by python-ironicclient version 2.7.0 or higher.

   The following examples assume you are using python-ironicclient version
   2.7.0 or higher.

   Export the following variable::

    export OS_BAREMETAL_API_VERSION=<API version>

#. The node's ``network_interface`` field should be set to a valid network
   interface. Valid interfaces are listed in the
   ``[DEFAULT]/enabled_network_interfaces`` configuration option in the
   ironic-conductor's configuration file. Set it to ``neutron`` to use the
   Networking service's ML2 driver::

     baremetal node create --network-interface neutron --driver ipmi

   .. note::
      If the ``[DEFAULT]/default_network_interface`` configuration option is
      set, the ``--network-interface`` option does not need to be specified
      when creating the node.

#. To update an existing node's network interface to ``neutron``, use the
   following commands::

     baremetal node set $NODE_UUID_OR_NAME \
         --network-interface neutron

#. Create a port as follows::

     baremetal port create $HW_MAC_ADDRESS --node $NODE_UUID \
         --local-link-connection switch_id=$SWITCH_MAC_ADDRESS \
         --local-link-connection switch_info=$SWITCH_HOSTNAME \
         --local-link-connection port_id=$SWITCH_PORT \
         --pxe-enabled true \
         --physical-network physnet1

   An Infiniband port requires client ID, while local link connection information will
   be populated by Infiniband Subnet Manager.
   The client ID consists of <12-byte vendor prefix>:<8 byte port GUID>.
   There is no standard process for deriving the port's MAC address ($HW_MAC_ADDRESS);
   it is vendor specific.
   For example, Mellanox ConnectX Family Devices prefix is ff:00:00:00:00:00:02:00:00:02:c9:00.
   If port GUID was f4:52:14:03:00:38:39:81 the client ID would be
   ff:00:00:00:00:00:02:00:00:02:c9:00:f4:52:14:03:00:38:39:81.
   Mellanox ConnectX Family Device's HW_MAC_ADDRESS consists of 6 bytes;
   the port GUID's lower 3 and higher 3 bytes. In this example it would be f4:52:14:38:39:81.
   Putting it all together, create an Infiniband port as follows::

     baremetal port create $HW_MAC_ADDRESS --node $NODE_UUID \
         --pxe-enabled true \
         --extra client-id=$CLIENT_ID \
         --physical-network physnet1

#. Create a Smart NIC port as follows::

     baremetal port create $HW_MAC_ADDRESS --node $NODE_UUID \
         --local-link-connection hostname=$HOSTNAME \
         --local-link-connection port_id=$REP_NAME \
         --pxe-enabled true \
         --physical-network physnet1 \
         --is-smartnic

   A Smart NIC port requires ``hostname`` which is the hostname of the Smart NIC,
   and ``port_id`` which is the representor port name within the Smart NIC.

#. Check the port configuration::

     baremetal port show $PORT_UUID

After these steps, the provisioning of the created node will happen in the
provisioning network, and then the node will be moved to the tenant network
that was requested.

Configuring the Networking service
==================================

In addition to configuring the Bare Metal service some additional configuration
of the Networking service is required to ensure ports for bare metal servers
are correctly programmed. This configuration will be determined by the Bare
Metal service network interfaces you have enabled and which top of rack
switches you have in your environment.

``flat`` network interface
--------------------------

In order for Networking service ports to correctly operate with the Bare Metal
service ``flat`` network interface the ``baremetal`` ML2 mechanism driver from
`networking-baremetal
<https://opendev.org/openstack/networking-baremetal>`_ needs to be
loaded into the Networking service configuration. This driver understands that
the switch should be already configured by the admin, and will mark the
networking service ports as successfully bound as nothing else needs to be
done.

#. Install the ``networking-baremetal`` library

   .. code-block:: console

     $ pip install networking-baremetal

#. Enable the ``baremetal`` driver in the Networking service ML2 configuration
   file

   .. code-block:: ini

     [ml2]
     mechanism_drivers = ovs,baremetal

``neutron`` network interface
-----------------------------

The ``neutron`` network interface allows the Networking service to program the
physical top of rack switches for the bare metal servers. To do this an ML2
mechanism driver which supports the ``baremetal`` VNIC type for the make and
model of top of rack switch in the environment must be installed and enabled.

This is a list of known top of rack ML2 mechanism drivers which work with the
``neutron`` network interface:

Cisco Nexus 9000 series
  To install and configure this ML2 mechanism driver see `Nexus Mechanism
  Driver Installation Guide
  <https://networking-cisco.readthedocs.io/projects/test/en/latest/install/ml2-nexus.html#nexus-mechanism-driver-installation-guide>`_.

FUJITSU CFX2000
  ``networking-fujitsu`` ML2 driver supports this switch. The documentation
  is available `here
  <https://opendev.org/x/networking-fujitsu/src/branch/master/doc/source/ml2_cfab.rst>`_.

Networking Generic Switch
  This is an ML2 mechanism driver built for testing against virtual bare metal
  environments and some switches that are not covered by hardware specific ML2
  mechanism drivers. More information is available in the project's `README
  <https://opendev.org/openstack/networking-generic-switch/src/branch/master/README.rst>`_.
