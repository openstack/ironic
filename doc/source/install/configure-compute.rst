Configure the Compute service to use the Bare Metal service
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

The Compute service needs to be configured to use the Bare Metal service's
driver. The configuration file for the Compute service is typically located at
``/etc/nova/nova.conf``.

.. note::

   As of the Newton release, it is possible to have multiple
   nova-compute services running the ironic virtual driver (in
   nova) to provide redundancy. Bare metal nodes are mapped to the
   services via a hash ring. If a service goes down, the
   available bare metal nodes are remapped to different services.

   Once active, a node will stay mapped to the same nova-compute
   even when it goes down. The node is unable to be managed through
   the Compute API until the service responsible returns to an active
   state.

The following configuration file must be modified on the Compute
service's controller nodes and compute nodes.

#. Change these configuration options in the Compute service configuration
   file (for example, ``/etc/nova/nova.conf``):

   .. code-block:: ini

       [default]

       # Defines which driver to use for controlling virtualization.
       # Enable the ironic virt driver for this compute instance.
       compute_driver=ironic.IronicDriver

       # Firewall driver to use with nova-network service.
       # Ironic supports only neutron, so set this to noop.
       firewall_driver=nova.virt.firewall.NoopFirewallDriver

       # Amount of memory in MB to reserve for the host so that it is always
       # available to host processes.
       # It is impossible to reserve any memory on bare metal nodes, so set
       # this to zero.
       reserved_host_memory_mb=0

       [filter_scheduler]

       # Enables querying of individual hosts for instance information.
       # Not possible for bare metal nodes, so set it to False.
       track_instance_changes=False

       [scheduler]

       # This value controls how often (in seconds) the scheduler should
       # attempt to discover new hosts that have been added to cells.
       # If negative (the default), no automatic discovery will occur.
       # As each bare metal node is represented by a separate host, it has
       # to be discovered before the Compute service can deploy on it.
       # The value here has to be carefully chosen based on a compromise
       # between the enrollment speed and the load on the Compute scheduler.
       # The recommended value of 2 minutes matches how often the Compute
       # service polls the Bare Metal service for node information.
       discover_hosts_in_cells_interval=120

   .. note::
        The alternative to setting the ``discover_hosts_in_cells_interval``
        option is to run the following command on any Compute controller node
        after each node is enrolled::

            nova-manage cell_v2 discover_hosts

#. If you have not switched to make use of :ref:`scheduling-resource-classes`,
   then the following options should be set as well. They must be removed from
   the configuration file after switching to resource classes.

   .. code-block:: ini

       [scheduler]

       # Use the ironic scheduler host manager. This host manager will consume
       # all CPUs, disk space, and RAM from a host as bare metal hosts, can not
       # be subdivided into multiple instances. Scheduling based on resource
       # classes does not use CPU/disk/RAM, so the default host manager can be
       # used in such cases.
       host_manager=ironic_host_manager

       [filter_scheduler]

       # Size of subset of best hosts selected by scheduler.
       # New instances will be scheduled on a host chosen randomly from a
       # subset of the 999 hosts. The big value is used to avoid race
       # conditions, when several instances are scheduled on the same bare
       # metal nodes. This is not a problem when resource classes are used.
       host_subset_size=999

       # This flag enables a different set of scheduler filters, which is more
       # suitable for bare metals. CPU, disk and memory filters are replaced
       # with their exact counterparts, to make sure only nodes strictly
       # matching the flavor are picked. These filters do not work with
       # scheduling based on resource classes only.
       use_baremetal_filters=True

#. Carefully consider the following option:

   .. code-block:: ini

       [compute]

       # This option will cause nova-compute to set itself to a disabled state
       # if a certain number of consecutive build failures occur. This will
       # prevent the scheduler from continuing to send builds to a compute
       # service that is consistently failing. In the case of bare metal
       # provisioning, however, a compute service is rarely the cause of build
       # failures. Furthermore, bare metal nodes, managed by a disabled
       # compute service, will be remapped to a different one. That may cause
       # the second compute service to also be disabled, and so on, until no
       # compute services are active.
       # If this is not the desired behavior, consider increasing this value or
       # setting it to 0 to disable this behavior completely.
       #consecutive_build_service_disable_threshold = 10

#. Change these configuration options in the ``ironic`` section.
   Replace:

   - ``IRONIC_PASSWORD`` with the password you chose for the ``ironic``
     user in the Identity Service
   - ``IRONIC_NODE`` with the hostname or IP address of the ironic-api node
   - ``IDENTITY_IP`` with the IP of the Identity server

   .. code-block:: ini

       [ironic]

       # Ironic authentication type
       auth_type=password

       # Keystone API endpoint
       auth_url=http://IDENTITY_IP:35357/v3

       # Ironic keystone project name
       project_name=service

       # Ironic keystone admin name
       username=ironic

       # Ironic keystone admin password
       password=IRONIC_PASSWORD

       # Ironic keystone project domain
       # or set project_domain_id
       project_domain_name=Default

       # Ironic keystone user domain
       # or set user_domain_id
       user_domain_name=Default

#. On the Compute service's controller nodes, restart the ``nova-scheduler``
   process:

   .. code-block:: console

       Fedora/RHEL7/CentOS7/SUSE:
         sudo systemctl restart openstack-nova-scheduler

       Ubuntu:
         sudo service nova-scheduler restart

#. On the Compute service's compute nodes, restart the ``nova-compute``
   process:

   .. code-block:: console

       Fedora/RHEL7/CentOS7/SUSE:
         sudo systemctl restart openstack-nova-compute

       Ubuntu:
         sudo service nova-compute restart
