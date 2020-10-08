.. _multitenancy:

=======================================
Multi-tenancy in the Bare Metal service
=======================================

Overview
========

It is possible to use dedicated tenant networks for provisioned nodes, which
extends the current Bare Metal service capabilities of providing flat networks.
This works in conjunction with the Networking service to allow provisioning of
nodes in a separate provisioning network. The result of this is that multiple
tenants can use nodes in an isolated fashion. However, this configuration does
not support trunk ports belonging to multiple networks.

Concepts
========

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
  physically connected to this network during their entire life cycle.

- ``neutron`` interface provides tenant-defined networking through the
  Networking service, separating tenant networks from each other and from the
  provisioning and cleaning provider networks. Nodes will move between these
  networks during their life cycle. This interface requires Networking service
  support for the switches attached to the baremetal servers so they can be
  programmed.

Local link connection
---------------------

The Bare Metal service allows ``local_link_connection`` information to be
associated with Bare Metal ports. This information is provided to the
Networking service's ML2 driver when a Virtual Interface (VIF) is attached. The
ML2 driver uses the information to plug the specified port to the tenant
network.

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

When attaching a virtual interface (VIF) to a node, the following ordered
criteria are used to select a suitable unattached port or port group:

* Require ports or port groups to not have a physical network or to have a
  physical network that matches one of the VIF's allowed physical networks.
* Prefer ports and port groups that have a physical network to ports and
  port groups that do not have a physical network.
* Prefer port groups to ports.  Prefer ports with PXE enabled.

Configuring the Bare Metal service
==================================

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
