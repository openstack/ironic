Configure Compute to use the Bare Metal service
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

The Compute service needs to be configured to use the Bare Metal service's
driver.  The configuration file for the Compute service is typically located at
``/etc/nova/nova.conf``.

.. note::
   This configuration file must be modified on the Compute service's
   controller nodes and compute nodes.

#. Change these configuration options in the ``default`` section, as follows:

    .. code-block:: ini

      [default]

      # Driver to use for controlling virtualization. Options
      # include: libvirt.LibvirtDriver, xenapi.XenAPIDriver,
      # fake.FakeDriver, baremetal.BareMetalDriver,
      # vmwareapi.VMwareESXDriver, vmwareapi.VMwareVCDriver (string
      # value)
      #compute_driver=<None>
      compute_driver=ironic.IronicDriver

      # Firewall driver (defaults to hypervisor specific iptables
      # driver) (string value)
      #firewall_driver=<None>
      firewall_driver=nova.virt.firewall.NoopFirewallDriver

      # The scheduler host manager class to use (string value)
      #scheduler_host_manager=host_manager
      scheduler_host_manager=ironic_host_manager

      # Virtual ram to physical ram allocation ratio which affects
      # all ram filters. This configuration specifies a global ratio
      # for RamFilter. For AggregateRamFilter, it will fall back to
      # this configuration value if no per-aggregate setting found.
      # (floating point value)
      #ram_allocation_ratio=1.5
      ram_allocation_ratio=1.0

      # Amount of disk in MB to reserve for the host (integer value)
      #reserved_host_disk_mb=0
      reserved_host_memory_mb=0

      # Flag to decide whether to use baremetal_scheduler_default_filters or not.
      # (boolean value)
      #scheduler_use_baremetal_filters=False
      scheduler_use_baremetal_filters=True

      # Determines if the Scheduler tracks changes to instances to help with
      # its filtering decisions (boolean value)
      #scheduler_tracks_instance_changes=True
      scheduler_tracks_instance_changes=False

      # New instances will be scheduled on a host chosen randomly from a subset
      # of the N best hosts, where N is the value set by this option.  Valid
      # values are 1 or greater. Any value less than one will be treated as 1.
      # For ironic, this should be set to a number >= the number of ironic nodes
      # to more evenly distribute instances across the nodes.
      #scheduler_host_subset_size=1
      scheduler_host_subset_size=9999999

#. Change these configuration options in the ``ironic`` section.
   Replace:

   - ``IRONIC_PASSWORD`` with the password you chose for the ``ironic``
     user in the Identity Service
   - ``IRONIC_NODE`` with the hostname or IP address of the ironic-api node
   - ``IDENTITY_IP`` with the IP of the Identity server

    .. code-block:: ini

      [ironic]

      # Ironic keystone admin name
      admin_username=ironic

      #Ironic keystone admin password.
      admin_password=IRONIC_PASSWORD

      # keystone API endpoint
      admin_url=http://IDENTITY_IP:35357/v2.0

      # Ironic keystone tenant name.
      admin_tenant_name=service

      # URL for Ironic API endpoint.
      api_endpoint=http://IRONIC_NODE:6385/v1

#. On the Compute service's controller nodes, restart the ``nova-scheduler``
   process:

    .. code-block:: console

      Fedora/RHEL7/CentOS7:
        sudo systemctl restart openstack-nova-scheduler

      Ubuntu:
        sudo service nova-scheduler restart

#. On the Compute service's compute nodes, restart the ``nova-compute``
   process:

    .. code-block:: console

      Fedora/RHEL7/CentOS7:
        sudo systemctl restart openstack-nova-compute

      Ubuntu:
        sudo service nova-compute restart
