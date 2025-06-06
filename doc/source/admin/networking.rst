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

- ``physical network`` - A physical network in the context of this document
  is a logical network fabric which works together. This *can* be represented
  for the purposes of modeling the infrastructure, and this terminology is
  somewhat over-used due to the similar filed name ``physical_network``
  which refers to the named and configured representation of the network
  fabric.

- ``vif`` or ``VIF`` - Virtual Interface which is best described as a Neutron
  port. For Ironic, VIFs are always referred to utilizing the Neutron port ID
  value, which is a UUID value. A VIF may be available across a limited number
  of physical networks, dependent upon the cloud's operating configuration
  and operating constraints.

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

- ``port`` - A port is the context of this document represents a physical
  or logical connection. For example, in the context of Ironic, a port is
  a possible physical connection which is connected for use to the underlying
  ``physical network``. Whereas in the context of Neutron, a port is a
  virtual network interface, or in Ironic terminology, a ``VIF``.

- ``port group`` - A composite set of ports, created utilizing Ironic's API
  to represent LACP or otherwise bonded network interfaces which exist between
  a network fabric and the physical bare metal node.

.. _network-interfaces:

Network interfaces
------------------

Network interface is one of the driver interfaces that manages network
switching for nodes. There are 3 network interfaces available in
the Ironic service:

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
  the network fabric. When using IPv6, use of the ``neutron`` interface is
  highly recommended as use of the ``dhcpv6-stateful`` configuration model
  for IPv6 with Neutron also automatically creates multiple address records
  for stateful address resolution.

To use these interfaces, they need to be enabled in *ironic.conf* utilizing
the :oslo.config:option:`enabled_network_interfaces` setting.

VIF Attachment flow
-------------------

When creating a virtual interface (VIF), the action occurs against the
Neutron Networking Service, such as by using the ``openstack port create``
command, and then the port ID is submitted to Ironic to facilitate a VIF
attachment.

.. NOTE::
   Instances created with Nova can have a Neutron port created under a variety
   of different circumstances. It is *highly* recommended, when using Nova,
   to explicitly declare the port(s) as part of your Nova instance creation
   request. When Nova asks Ironic to deploy a node, nova attempts to record
   all VIFs the user requested to be attached into Ironic, and then generate
   user friendly metadata as a result.

When a virtual interface (VIF) is requested to be attached to a node via the
Ironic API, the following ordered criteria are used to select a suitable
unattached port or port group:

* Require ports or port groups to not have a physical network or to have a
  physical network that matches one of the VIF's available physical networks
  which it may be configured across.

* Prefer ports and port groups which have a physical network to ports and
  port groups which do not have a physical network.

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

As all VIFs are required to be attached to a port group or independent
ports, the maximum number of VIFs is determined by the number of configured
and available ports represented in Ironic, as framed by the suitability
criteria noted above.

Ironic goes to attach *any* supplied, selected, or even self-created
VIFs, in two distinct steps.

If a host is *not* active:

The first step, as a result of
`bug 2106073 <https://bugs.launchpad.net/ironic/+bug/2106073>`_,
Ironic provides an initial ``host_id`` to Neutron so neutron can perform
any deferred address assignment to enable appropriate network mapping. This
initial binding lacks all detail to enable binding to an exact port.
For a short period of time, the VIF binding may show as "ACTIVE" in Neutron.

.. NOTE::
   If the port was bound in *advance* of being submitted to Ironic,
   and we must perform an initial bind, the port will be unbound and rebound
   as part of the workflow.

Once we're handing the instance over to the user, Ironic sets the physical
port's MAC address, and provides additional context, such as the physical
switch and switchport metadata which may be used. This action effectively
"re-binds" the port, and the port state in Neutron can change as a result
if binding is successful or fails. That may, ultimately, have no realistic
impact to availability of ability to pass traffic over an interface, but
can be rooted in the overall ``network_interface`` driver in use as well.

.. NOTE::
   Ironic's ``network_interface`` driver selection does influence the base
   binding model behavior and as such the resulting state as reported by
   Neutron. Specifically ``flat`` assumes a pre-wired, static, never changing
   physical network. Neutron port states indicating a failure when using the
   ``flat`` interface is often more a sign of the ``networking-baremetal``
   ML2 plugin not being configured in Neutron.
   The ``neutron`` interface is far more dynamic and the binding state can
   generally be relied upon if any operator configured ML2 plugins are
   functional.

If the host in in an *active* state:

Ironic explicitly sets the physical port's MAC address for which the
VIF will be bound, and is immediately attached to the host with any
required metadata for port binding, which is then transmitted to Neutron.

A port binding failure will, by default, forcibly abort deployment on the
``neutron`` interface to prevent scenarios where instances appear as
``ACTIVE`` but are actually connected to the wrong network (e.g., remaining
on the provisioning network instead of their assigned VLAN), leading to
non-functional networking.

This behavior can be adjusted using the
:oslo.config:option:`neutron.fail_on_port_binding_failure` configuration
option (default: ``true``). When set to ``false``, failures will only log
a warning.

For Smart NICs, port binding failures are treated as fatal regardless of the
global configuration setting, as proper network configuration is essential for
these devices.

Operators can override both the global configuration and Smart NIC default
behavior on a per-node basis using the ``fail_on_binding_failure`` field in
the node's ``driver_info``.

When Ironic goes to unbind the VIF, Ironic makes a request for Neutron to
"reset" the assigned MAC address in order to avoid conflicts with Neutron's
unique hardware MAC address requirement.

Basic Provisioning flow
~~~~~~~~~~~~~~~~~~~~~~~

When provisioning, Ironic will attempt to attach all PXE enabled
ports to the *provisioning network*. A modifier for this behavior is the
:oslo.config:option:`neutron.add_all_ports` option, where ironic will
attempt to bind all ports to the required service network beyond the
ironic ports with ``pxe_enabled`` set to ``True``.

After provisioning work has been completed, and prior to the node being
moved to the ``ACTIVE`` ``provision_state``, the previously attached ports
are unbound.

In the case of the ``network_interface`` set to ``flat``, the requested VIF(s)
utilized for all binding configurations in all states.

In the case of the ``network_interface`` set to ``neutron``, the user requested
VIFs are attached to the Ironic node for the first time, as the time spent in
the *provisioning network* was utilizing VIFs which Ironic created and then
deleted as part of the baremetal node's movement through the state machine.

The same flow and logic applies to *cleaning*, *service*, and *rescue*
workflows.

How are VIFs configured on the deployed machine
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

.. _multitenancy-physnets:

Physical networks
-----------------

An Ironic port may be associated with a physical network using its
``physical_network`` field. Ironic uses this information when
mapping between virtual ports in Neutron and physical ports and
port groups. A port's physical network field is optional, and if not
set then any VIF may be mapped to that port, provided that no free
Ironic port with a suitable physical network assignment exists.
When set, its value must be a name that corresponds to a physical network
in Neutron for the networking-baremetal integration to properly reconcile
the port. This has to be a name (not a UUID) since physical networks are
configured in Neutron by name.

The physical network of a port group is defined by the physical network of its
constituent ports. The Ironic service ensures that all ports in a port
group have the same value in their physical network field.

The ``physical_network`` setting is used to have divided network fabrics which
may carry different sets of traffic, and is intended to help model the reality
multiple network fabrics into the overall operation with Neutron.

Local link connection
---------------------

Use of the ``neutron`` network-interfaces_ requires the Ironic port
``local_link_connection`` information to be populated for each Ironic port
on a node in Ironic. This information is provided to the Neutron networking
service's ML2 driver when a Virtual Interface (VIF) is attached. The ML2
driver uses the information to plug the specified port to the tenant network.

This information is typically populated through the introspection process
by using LLDP data being broadcast from the switches, but may need to be
manually set or changed in the case of a physical networking change, such as
when a baremetal port's cable has been moved to a different port on a switch,
or the switch has been replaced.

.. note::
   For auto-discovery of values to work as part of introspection,
   switches must have LLDP enabled.

.. note::
   Decoding LLDP data is performed as a best effort action. Some switch
   vendors, or changes in switch vendor firmware may impact field decoding.
   While this is rare, please report issues such as this to the Ironic
   project as bugs.

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

Example setting of local link connection information
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Below is an example command you can use as a basis to set the
required information into Ironic.

.. code-block:: shell

  baremetal port create <physical_mac_address> --node <node_uuid> \
       --local-link-connection switch_id=<switch_mac_address> \
       --local-link-connection switch_info=<switch_hostname> \
       --local-link-connection port_id=<switch_port_for_connection> \
       --pxe-enabled true \
       --physical-network physnet1

.. WARNING::
   Depending on your ML2 plugin, you may need different or additional data
   to be provided as part of the ``local_link_connection`` information.

Alternatively, if you just need to update an existing value, such as the
``port_id`` value due to a cabling change, you can use the *baremetal port
set* command.

.. code-block:: shell

  baremetal port set --node <node_uuid> \
      --local-link-connection port_id=<updated_switch_port_for_connection \
      <baremetal_port_uuid>

Example setting an Infiniband Port with local link connection information
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Infiniband port requires require use of a client ID, where local link
connection information is intended to be populated by the Infiniband
Subnet Manager.

The client ID consists of <12-byte vendor prefix>:<8 byte port GUID>.
There is no standard process for deriving the port's MAC address ($HW_MAC_ADDRESS);
it is vendor specific.

For example, Mellanox ConnectX Family Devices prefix is ff:00:00:00:00:00:02:00:00:02:c9:00.
If port GUID was f4:52:14:03:00:38:39:81 the client ID would be
ff:00:00:00:00:00:02:00:00:02:c9:00:f4:52:14:03:00:38:39:81.

Mellanox ConnectX Family Device's HW_MAC_ADDRESS consists of 6 bytes;
the port GUID's lower 3 and higher 3 bytes. In this example it would be f4:52:14:38:39:81.
Putting it all together, create an Infiniband port as follows.

.. code-block:: shell

  baremetal port create <physical_mac_address> --node <node_uuid> \
       --pxe-enabled true \
       --extra client-id=<client_id> \
       --physical-network physnet1

Example setting a Smart NIC port
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Smart NIC usage is a very specialized use case where an ML2 plugin
as part of an infrastructure or the ``neutron-l2-agent`` is installed
in the operating system on the Smart NIC *and* the service is configured
to speak with the rest of the OpenStack deployment.

When a Smart NIC is present which is integrated in this fashion,
Ironic needs to be aware to ensure overall chasiss power is in a state
which is suitable to ensure that the port can be attached. i.e. The card
can be programmed remotely.

To signal to Ironic the device and connection is supplied via a
Smart NIC, use the following command. This requires the ``hostname``
of the operating system inside the Smart NIC to asserted along with
the ``port_id`` value to match the internal port representation name.

.. code-block:: shell

  baremetal port create <physical_mac_address> --node <node_uuid> \
       --local-link-connection hostname=<smartnic_hostname> \
       --local-link-connection port_id=<internal_port_name> \
       --pxe-enabled true \
       --physical-network physnet1 \
       --is-smartnic

Configuring and using Network Multi-tenancy
===========================================

See the :ref:`configure-tenant-networks` section in the installation guide for
the Bare Metal (Ironic) service.


Configuring the Networking service
==================================

In addition to configuring Ironic, some additional configuration
of the Neutron is required to ensure ports for bare metal servers
are correctly programmed *and* represent a proper state, depending on your
use model.

This configuration is determined by the Ironic network interface drivers
you have enabled, which top of rack switches you have in your environment,
and ultimately the structural model of your network, as in if your using
``physical_network`` values.

Physnet Mapping
---------------

When using physnet mapping, it is critical for proper instance scheduling for
network resources to be informed of the physical network mappins which
are represented in relation to the hosts in the deployment.

This takes the form of the ``ironic-neutron-agent`` which operators should
deploy. Information on how to setup and configure this agent can be located
at in the networking-baremetal installation documentation for the
`ironic-neutron-agent <https://docs.openstack.org/networking-baremetal/latest/install/index.html#configure-ironic-neutron-agent>`_.

``flat`` network interface
--------------------------

In order for Networking service ports to correctly operate with the Ironic
service ``flat`` network interface the ``baremetal`` ML2 mechanism driver from
`networking-baremetal
<https://opendev.org/openstack/networking-baremetal>`_ needs to be
loaded into the Neutron configuration. This driver understands that
the switch should be already configured by the admin, and will mark the
networking service ports as successfully bound as nothing else needs to be
done for the ``VNIC_BAREMETAL`` binding requests which made by Ironic on
behalf of users seeking their ports to be attached.

#. Install the ``networking-baremetal`` library

   .. code-block:: console

     $ pip install networking-baremetal

#. Enable the ``baremetal`` driver in the Networking service ML2 configuration
   file

   .. code-block:: ini

     [ml2]
     mechanism_drivers = ovs,baremetal

#. Restart your Neutron API service, which houses the ML2 mechanism drivers.

``neutron`` network interface
-----------------------------

The ``neutron`` network interface allows the Networking service to program the
physical top of rack switches for the bare metal servers. To do this an ML2
mechanism driver which supports the ``baremetal`` VNIC type for the make and
model of top of rack switch in the environment must be installed and enabled.

One case where you may wish to prefer the ``neutron`` network interface, even
when your architecture is statically configured interfaces similar to ``flat``
networks, is when your using IPv6. Various hardware, bootloader, and Operating
System DHCP clients utilize different techniques for generating the host
identifier string which DHCP servers utilize to track IPv6 hosts. The
``neutron`` interface generates additional IPv6 DHCP entries to account for
situations such as this, where as the ``flat`` interface is unable to do so.

This is a list of known top of rack ML2 mechanism drivers which work with the
``neutron`` network interface.

Community ML2 Drivers
~~~~~~~~~~~~~~~~~~~~~

Community ML2 drivers are drivers maintained by the community, and can be
expected to generally focus on the minimum viable need to facilitate use
cases.

Networking Generic Switch
  This ML2 mechanism driver is generally viewed as the "go-to" solution to get
  started. It is modeled upon remote switch configuration using text interfaces,
  and the minimum feature for each switch is "setting a port on a vlan".
  This ML2 driver is tested in CI as it also supports management of some virtual
  machine networking as Ironic uses it in CI. It is also relatively simple to
  modify to enable support for newer models, or changes in vendor command
  lines. It also has some defects and issues, but is still viewed as the
  first "go-to" solution to get started.
  More information is available in the project's `README
  <https://opendev.org/openstack/networking-generic-switch/src/branch/master/README.rst>`_.
  The project's documentation can also be found
  `here <https://docs.openstack.org/networking-generic-switch/latest/>`_.

Networking Baremetal
  This ML2 mechanism driver, which we briefly cover in the ``flat`` network
  interface settings earlier in this document, also has support for asserting
  configuration to remote switches using
  `Netconf <https://en.wikipedia.org/wiki/NETCONF>`_ with the
  `OpenConfig <https://www.openconfig.net/>`_ data model. This, similar to
  the issues with DMTF Redfish, means that it doesn't work for every Netconf
  supported switch.
  More information can be found at networking-baremetal
  `documentation <https://docs.openstack.org/networking-baremetal>`_
  and
  `device-drivers documentation <https://docs.openstack.org/networking-baremetal/latest/configuration/ml2/device_drivers/index.html>`_
  with some additional detail covered on how to configure
  `devices to manage <https://docs.openstack.org/networking-baremetal/latest/install/index.html#add-devices-switches-to-manage>`_.


Vendor ML2 Drivers
~~~~~~~~~~~~~~~~~~

Cisco Nexus (networking-cisco)
  To install and configure this ML2 mechanism driver see `Nexus Mechanism
  Driver Installation Guide
  <https://networking-cisco.readthedocs.io/projects/test/en/latest/install/ml2-nexus.html#nexus-mechanism-driver-installation-guide>`_.
  This driver does appear to be maintained by the vendor, but the Ironic
  community is unaware of it's status otherwise.

Arista (networking-arista)
  The networking-arista project does appear to have some logic to handle
  the VNIC_BAREMETAL requests, and Arista was deeply involved when the
  overall model of ML2 switch orchustration was created.
  Limited information is available, but the repository can be found at
  on OpenDev in the `x/networking-arista <https://opendev.org/x/networking-arista>`_
  repository.

Previously in this list we included networking-fujitsu, however it
no longer appears maintained. Customers of Fujitsu products should
inquire with Fujitsu directly.
