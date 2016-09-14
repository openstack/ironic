.. _configure-networking:

Configure Networking to communicate with the bare metal server
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

You need to configure Networking so that the bare metal server can communicate
with the Networking service for DHCP, PXE boot and other requirements.
This section covers configuring Networking for a single flat network for bare
metal provisioning.

You will also need to provide Bare Metal service with the MAC address(es) of
each node that it is provisioning; Bare Metal service in turn will pass this
information to Networking service for DHCP and PXE boot configuration.
An example of this is shown in the :ref:`enrollment` section.

#. Edit ``/etc/neutron/plugins/ml2/ml2_conf.ini`` and modify these:

   .. code-block:: ini

      [ml2]
      type_drivers = flat
      tenant_network_types = flat
      mechanism_drivers = openvswitch

      [ml2_type_flat]
      flat_networks = physnet1

      [securitygroup]
      firewall_driver = neutron.agent.linux.iptables_firewall.OVSHybridIptablesFirewallDriver
      enable_security_group = True

      [ovs]
      bridge_mappings = physnet1:br-eth2
      # Replace eth2 with the interface on the neutron node which you
      # are using to connect to the bare metal server

#. If neutron-openvswitch-agent runs with ``ovs_neutron_plugin.ini`` as the input
   config-file, edit ``ovs_neutron_plugin.ini`` to configure the bridge mappings
   by adding the [ovs] section described in the previous step, and restart the
   neutron-openvswitch-agent.

#. Add the integration bridge to Open vSwitch:

   .. code-block:: console

      $ ovs-vsctl add-br br-int

#. Create the br-eth2 network bridge to handle communication between the
   OpenStack services (and the Bare Metal services) and the bare metal nodes
   using eth2.
   Replace eth2 with the interface on the network node which you are using to
   connect to the Bare Metal service:

   .. code-block:: console

      $ ovs-vsctl add-br br-eth2
      $ ovs-vsctl add-port br-eth2 eth2

#. Restart the Open vSwitch agent:

   .. code-block:: console

      # service neutron-plugin-openvswitch-agent restart

#. On restarting the Networking service Open vSwitch agent, the veth pair
   between the bridges br-int and br-eth2 is automatically created.

   Your Open vSwitch bridges should look something like this after
   following the above steps:

   .. code-block:: console

      $ ovs-vsctl show

          Bridge br-int
              fail_mode: secure
              Port "int-br-eth2"
                  Interface "int-br-eth2"
                      type: patch
                      options: {peer="phy-br-eth2"}
              Port br-int
                  Interface br-int
                      type: internal
          Bridge "br-eth2"
              Port "phy-br-eth2"
                  Interface "phy-br-eth2"
                      type: patch
                      options: {peer="int-br-eth2"}
              Port "eth2"
                  Interface "eth2"
              Port "br-eth2"
                  Interface "br-eth2"
                      type: internal
          ovs_version: "2.3.0"

#. Create the flat network on which you are going to launch the
   instances:

   .. code-block:: console

      $ neutron net-create --tenant-id $TENANT_ID sharednet1 --shared \
            --provider:network_type flat --provider:physical_network physnet1

#. Create the subnet on the newly created network:

   .. code-block:: console

      $ neutron subnet-create sharednet1 $NETWORK_CIDR --name $SUBNET_NAME \
            --ip-version=4 --gateway=$GATEWAY_IP --allocation-pool \
            start=$START_IP,end=$END_IP --enable-dhcp

