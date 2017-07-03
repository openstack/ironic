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

Network interface is one of the driver interfaces that manages network
switching for nodes. There are 3 network interfaces available in
the Bare Metal service:

- ``noop`` interface is used for standalone deployments, and does not perform
  any network switching;

- ``flat`` interface places all provisioned nodes and nodes being deployed into
  a single layer 2 network, separated from the cleaning network;

- ``neutron`` interface provides tenant-defined networking by integrating with
  the Networking service, while also separating tenant networks from the
  provisioning and cleaning provider networks.

Configuring the Bare Metal service
==================================

See the `Configure tenant networks`_ section in the installation guide for the
Bare Metal service.

.. _`Configure tenant networks`: http://docs.openstack.org/project-install-guide/baremetal/draft/configure-tenant-networks.html

Configuring nodes
=================

#. Multi-tenancy support was added in the 1.20 API version. The following
   examples assume you are using python-ironicclient version 1.5.0 or higher.
   They show the usage of both ``ironic`` and ``openstack baremetal`` commands.

   If you're going to use ``ironic`` command, set the following variable in
   your shell environment::

    export IRONIC_API_VERSION=1.20

   If you're using ironic client plugin for openstack client via
   ``openstack baremetal`` commands, export the following variable::

    export OS_BAREMETAL_API_VERSION=1.20

#. The node's ``network_interface`` field should be set to a valid network
   interface. Valid interfaces are listed in the
   ``[DEFAULT]/enabled_network_interfaces`` configuration option in the
   ironic-conductor's configuration file. Set it to ``neutron`` to use the
   Networking service's ML2 driver:

   - ``ironic`` command::

      ironic node-create --network-interface neutron \
      --driver agent-ipmitool

   - ``openstack`` command::

      openstack baremetal node create --network-interface neutron \
      --driver agent-ipmitool

   .. note::
      If the ``[DEFAULT]/default_network_interface`` configuration option is
      set, the ``--network-interface`` option does not need to be specified
      when creating the node.

#. To update an existing node's network interface to ``neutron``, use the
   following commands:

   - ``ironic`` command::

      ironic node-update $NODE_UUID_OR_NAME add network_interface=neutron

   - ``openstack`` command::

      openstack baremetal node set $NODE_UUID_OR_NAME \
      --network-interface neutron

#. The Bare Metal service provides the ``local_link_connection`` information to
   the Networking service's ML2 driver. The ML2 driver uses that information to
   plug the specified port to the tenant network.

   .. list-table:: ``local_link_connection`` fields
      :header-rows: 1

      * - Field
        - Description
      * - ``switch_id``
        - Required. Identifies a switch and can be a MAC address or an
          OpenFlow-based ``datapath_id``.
      * - ``port_id``
        - Required. Port ID on the switch, for example, Gig0/1.
      * - ``switch_info``
        - Optional. Used to distinguish different switch models or other
          vendor-specific identifier. Some ML2 plugins may require this
          field.

   Create a port as follows:

   - ``ironic`` command::

      ironic port-create -a $HW_MAC_ADDRESS -n $NODE_UUID \
      -l switch_id=$SWITCH_MAC_ADDRESS -l switch_info=$SWITCH_HOSTNAME \
      -l port_id=$SWITCH_PORT --pxe-enabled true

   - ``openstack`` command::

      openstack baremetal port create $HW_MAC_ADDRESS --node $NODE_UUID \
      --local-link-connection switch_id=$SWITCH_MAC_ADDRESS \
      --local-link-connection switch_info=$SWITCH_HOSTNAME \
      --local-link-connection port_id=$SWITCH_PORT --pxe-enabled true

#. Check the port configuration:

   - ``ironic`` command::

      ironic port-show $PORT_UUID

   - ``openstack`` command::

      openstack baremetal port show $PORT_UUID

After these steps, the provisioning of the created node will happen in the
provisioning network, and then the node will be moved to the tenant network
that was requested.
