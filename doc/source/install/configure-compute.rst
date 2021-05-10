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

            nova-manage cell_v2 discover_hosts --by-service

#. Consider enabling the following option on controller nodes:

   .. code-block:: ini

     [filter_scheduler]

     # Enabling this option is beneficial as it reduces re-scheduling events
     # for ironic nodes when scheduling is based on resource classes,
     # especially for mixed hypervisor case with host_subset_size = 1.
     # However enabling it will also make packing of VMs on hypervisors
     # less dense even when scheduling weights are completely disabled.
     #shuffle_best_same_weighed_hosts = false


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
       auth_url=http://IDENTITY_IP:5000/v3

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

       Fedora/RHEL8/CentOS8/SUSE:
         sudo systemctl restart openstack-nova-scheduler

       Ubuntu:
         sudo service nova-scheduler restart

#. On the Compute service's compute nodes, restart the ``nova-compute``
   process:

   .. code-block:: console

       Fedora/RHEL8/CentOS8/SUSE:
         sudo systemctl restart openstack-nova-compute

       Ubuntu:
         sudo service nova-compute restart
