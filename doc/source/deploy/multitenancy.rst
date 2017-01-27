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

Below is an example flow of how to set up the Bare Metal service so that node
provisioning will happen in a multi-tenant environment (which means using the
``neutron`` network interface as stated above):

#. Network interfaces can be enabled on ironic-conductor by adding them to the
   ``enabled_network_interfaces`` configuration option under the ``default``
   section of the configuration file::

    [DEFAULT]
    ...
    enabled_network_interfaces=noop,flat,neutron

   Keep in mind that, ideally, all ironic-conductors should have the same list
   of enabled network interfaces, but it may not be the case during
   ironic-conductor upgrades. This may cause problems if one of the
   ironic-conductors dies and some node that is taken over is mapped to an
   ironic-conductor that does not support the node's network interface.
   Any actions that involve calling the node's driver will fail until that
   network interface is installed and enabled on that ironic-conductor.

#. It is recommended to set the default network interface via the
   ``default_network_interface`` configuration option under the ``default``
   section of the configuration file::

    [DEFAULT]
    ...
    default_network_interface=neutron

   This default value will be used for all nodes that don't have a network
   interface explicitly specified in the creation request.

   If this configuration option is not set, the default network interface is
   determined by looking at the ``[dhcp]dhcp_provider`` configuration option
   value. If it is ``neutron``, then ``flat`` network interface becomes the
   default, otherwise ``noop`` is the default.

#. Define a provider network in the Networking service, which we shall refer to
   as the "provisioning" network, and add it in the ``neutron`` section of the
   ironic-conductor configuration file. Using the ``neutron`` network interface
   requires that ``provisioning_network`` and ``cleaning_network``
   configuration options are set to valid identifiers (UUID or name) of
   networks in the  Networking service. If these options are not set correctly,
   cleaning or provisioning will fail to start::

    [neutron]
    ...
    cleaning_network=$CLEAN_UUID_OR_NAME
    provisioning_network=$PROVISION_UUID_OR_NAME

   Please refer to `Configure the Bare Metal service for cleaning`_ for more
   information about cleaning.

   .. warning::
      Please make sure that the Bare Metal service has exclusive access to the
      provisioning and cleaning networks. Spawning instances by non-admin users
      in these networks and getting access to the Bare Metal service's control
      plane is a security risk. For this reason, the provisioning and cleaning
      networks should be configured as non-shared networks in the ``admin``
      tenant.

   .. note::
      Spawning a bare metal instance onto the provisioning network is
      impossible, the deployment will fail. The node should be deployed onto a
      different network than the provisioning network. When you boot a bare
      metal instance from the Compute service, you should choose a different
      network in the Networking service for your instance.

   .. note::
      The "provisioning" and "cleaning" networks may be the same network or
      distinct networks. To ensure that communication between the Bare Metal
      service and the deploy ramdisk works, it is important to ensure that
      security groups are disabled for these networks, *or* that the default
      security groups allow:

      * DHCP
      * TFTP
      * egress port used for the Bare Metal service (6385 by default)
      * ingress port used for ironic-python-agent (9999 by default)
      * if using the iSCSI deploy method (``pxe_*`` and ``iscsi_*`` drivers),
        the ingress port used for iSCSI (3260 by default)
      * if using the direct deploy method (``agent_*`` drivers), the egress
        port used for the Object Storage service (typically 80 or 443)
      * if using iPXE, the egress port used for the HTTP server running
        on the ironic-conductor nodes (typically 80).


#. This step is optional and applicable only if you want to use security
   groups during provisioning and/or cleaning of the nodes. If not specified,
   default security groups are used.

   #. Define security groups in the Networking service, to be used for
      provisioning and/or cleaning networks.

   #. Add the list of these security group UUIDs under the ``neutron`` section
      of ironic-conductor's configuration file as shown below::

        [neutron]
        ...
        cleaning_network=$CLEAN_UUID_OR_NAME
        cleaning_network_security_groups=[$LIST_OF_CLEAN_SECURITY_GROUPS]
        provisioning_network=$PROVISION_UUID_OR_NAME
        provisioning_network_security_groups=[$LIST_OF_PROVISION_SECURITY_GROUPS]

      Multiple security groups may be applied to a given network, hence,
      they are specified as a list.
      The same security group(s) could be used for both provisioning and
      cleaning networks.

   .. warning::
       If security groups are configured as described above, do not
       set the "port_security_enabled" flag to False for the corresponding
       Networking service's network or port. This will cause the deploy to fail.

       For example: if ``provisioning_network_security_groups`` configuration
       option is used, ensure that "port_security_enabled" flag for the
       provisioning network is set to True. This flag is set to True by
       default; make sure not to override it by manually setting it to False.

#. Install and configure a compatible ML2 mechanism driver which supports bare
   metal provisioning for your switch. See `ML2 plugin configuration manual
   <http://docs.openstack.org/networking-guide/config-ml2.html>`_
   for details.

#. Restart the ironic-conductor and ironic-api services after the
   modifications:

   - Fedora/RHEL7/CentOS7::

      sudo systemctl restart openstack-ironic-api
      sudo systemctl restart openstack-ironic-conductor

   - Ubuntu::

      sudo service ironic-api restart
      sudo service ironic-conductor restart

#. Make sure that the ironic-conductor is reachable over the provisioning
   network by trying to download a file from a TFTP server on it, from some
   non-control-plane server in that network::

    tftp $TFTP_IP -c get $FILENAME

   where FILENAME is the file located at the TFTP server.

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

.. _`Configure the Bare Metal service for cleaning`: http://docs.openstack.org/project-install-guide/baremetal/draft/configure-cleaning.html
