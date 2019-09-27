.. _configure-tenant-networks:

Configure tenant networks
=========================

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
   as the "provisioning" network. Using the ``neutron`` network interface
   requires that ``provisioning_network`` and ``cleaning_network``
   configuration options are set to valid identifiers (UUID or name) of
   networks in the Networking service. If these options are not set correctly,
   cleaning or provisioning will fail to start. There are two ways to set these
   values:

   - Under the ``neutron`` section of ironic configuration file:

     .. code-block:: ini

      [neutron]
      cleaning_network = $CLEAN_UUID_OR_NAME
      provisioning_network = $PROVISION_UUID_OR_NAME

   - Under ``provisioning_network`` and ``cleaning_network`` keys of the node's
     ``driver_info`` field as ``driver_info['provisioning_network']`` and
     ``driver_info['cleaning_network']`` respectively.

   .. note::
      If these ``provisioning_network`` and ``cleaning_network`` values are
      not specified in node's `driver_info` then ironic falls back to the
      configuration in the ``neutron`` section.

   Please refer to :doc:`configure-cleaning` for more information about
   cleaning.

   .. warning::
      Please make sure that the Bare Metal service has exclusive access to the
      provisioning and cleaning networks. Spawning instances by non-admin users
      in these networks and getting access to the Bare Metal service's control
      plane is a security risk. For this reason, the provisioning and cleaning
      networks should be configured as non-shared networks in the ``admin``
      tenant.

   .. note::
      When using the ``flat`` network interface, bare metal instances are
      normally spawned onto the "provisioning" network. This is not supported
      with the ``neutron`` interface and the deployment will fail. Please
      ensure a different network is chosen in the Networking service when
      a bare metal instance is booted from the Compute service.

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
      * if using :ref:`iscsi-deploy`, the ingress port used for iSCSI
        (3260 by default)
      * if using :ref:`direct-deploy`, the egress port used for the Object
        Storage service (typically 80 or 443)
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
   <https://docs.openstack.org/neutron/train/admin/config-ml2.html>`_
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

See :ref:`multitenancy` for required node configuration.
