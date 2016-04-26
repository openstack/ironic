.. _install-guide:

==================
Installation Guide
==================

This document is continually updated and reflects the latest
available code of the Bare Metal service (ironic).
Users of releases may encounter differences and are encouraged
to look at earlier versions of this document for guidance.


Service overview
================

The Bare Metal service is a collection of components that provides support to
manage and provision physical machines.

Also known as the ``ironic`` project, the Bare Metal service may, depending
upon configuration, interact with several other OpenStack services. This
includes:

- the OpenStack Telemetry module (ceilometer) for consuming the IPMI metrics
- the OpenStack Identity service (keystone) for request authentication and to
  locate other OpenStack services
- the OpenStack Image service (glance) from which to retrieve images and image meta-data
- the OpenStack Networking service (neutron) for DHCP and network configuration
- the OpenStack Compute service (nova) works with the Bare Metal service and acts as
  a user-facing API for instance management, while the Bare Metal service provides
  the admin/operator API for hardware management.
  The OpenStack Compute service also provides scheduling facilities (matching
  flavors <-> images <-> hardware), tenant quotas, IP assignment, and other
  services which the Bare Metal service does not, in and of itself, provide.

- the OpenStack Block Storage (cinder) provides volumes, but this aspect is not yet available.

The Bare Metal service includes the following components:

- ironic-api: A RESTful API that processes application requests by sending
  them to the ironic-conductor over RPC.
- ironic-conductor: Adds/edits/deletes nodes; powers on/off nodes with
  ipmi or ssh; provisions/deploys/decommissions bare metal nodes.
- ironic-python-agent: A python service which is run in a temporary ramdisk to
  provide ironic-conductor service(s) with remote access and in-band hardware
  control.
- python-ironicclient: A command-line interface (CLI) for interacting with
  the Bare Metal service.

Additionally, the Bare Metal service has certain external dependencies, which are
very similar to other OpenStack services:

- A database to store hardware information and state. You can set the database
  back-end type and location. A simple approach is to use the same database
  back end as the Compute service. Another approach is to use a separate
  database back-end to further isolate bare metal resources (and associated
  metadata) from users.
- A queue. A central hub for passing messages, such as RabbitMQ.
  It should use the same implementation as that of the Compute service.

Optionally, one may wish to utilize the following associated projects for
additional functionality:

- ironic-inspector_; An associated service which performs in-band hardware
  introspection by PXE booting unregistered hardware into a "discovery ramdisk".
- diskimage-builder_; May be used to customize machine images, create and
  discovery deploy ramdisks, if necessary.
- bifrost_; a set of Ansible playbooks that automates the task of deploying a
  base image onto a set of known hardware using ironic.

.. _ironic-inspector: https://github.com/openstack/ironic-inspector
.. _diskimage-builder: https://github.com/openstack/diskimage-builder
.. _bifrost: https://github.com/openstack/bifrost


.. todo: include coreos-image-builder reference here, once the split is done


Install and configure prerequisites
===================================

The Bare Metal service is a collection of components that provides support to
manage and provision physical machines. You can configure these components to
run on separate nodes or the same node. In this guide, the components run on
one node, typically the Compute Service's compute node.

This section shows you how to install and configure the components.

It assumes that the Identity, Image, Compute, and Networking services
have already been set up.

Configure the Identity service for the Bare Metal service
---------------------------------------------------------

#. Create the Bare Metal service user (for example,``ironic``).
   The service uses this to authenticate with the Identity service.
   Use the ``service`` tenant and give the user the ``admin`` role::

    openstack user create --password IRONIC_PASSWORD \
    --email ironic@example.com ironic
    openstack role add --project service --user ironic admin

#. You must register the Bare Metal service with the Identity service so that
   other OpenStack services can locate it. To register the service::

    openstack service create --name ironic --description \
    "Ironic baremetal provisioning service" baremetal

#. Use the ``id`` property that is returned from the Identity service when
   registering the service (above), to create the endpoint,
   and replace IRONIC_NODE with your Bare Metal service's API node::

    openstack endpoint create --region RegionOne \
    --publicurl http://IRONIC_NODE:6385 \
    --internalurl http://IRONIC_NODE:6385 \
    --adminurl http://IRONIC_NODE:6385 \
    baremetal

Set up the database for Bare Metal
----------------------------------

The Bare Metal service stores information in a database. This guide uses the
MySQL database that is used by other OpenStack services.

#. In MySQL, create an ``ironic`` database that is accessible by the
   ``ironic`` user. Replace IRONIC_DBPASSWORD
   with a suitable password::

    # mysql -u root -p
    mysql> CREATE DATABASE ironic CHARACTER SET utf8;
    mysql> GRANT ALL PRIVILEGES ON ironic.* TO 'ironic'@'localhost' \
    IDENTIFIED BY 'IRONIC_DBPASSWORD';
    mysql> GRANT ALL PRIVILEGES ON ironic.* TO 'ironic'@'%' \
    IDENTIFIED BY 'IRONIC_DBPASSWORD';

Install the Bare Metal service
------------------------------

#. Install from packages and configure services::

    Ubuntu 14.04 (trusty) or higher:
        sudo apt-get install ironic-api ironic-conductor python-ironicclient

    Fedora 21/RHEL7/CentOS7:
        sudo yum install openstack-ironic-api openstack-ironic-conductor \
        python-ironicclient
        sudo systemctl enable openstack-ironic-api openstack-ironic-conductor
        sudo systemctl start openstack-ironic-api openstack-ironic-conductor

    Fedora 22 or higher:
        sudo dnf install openstack-ironic-api openstack-ironic-conductor \
        python-ironicclient
        sudo systemctl enable openstack-ironic-api openstack-ironic-conductor
        sudo systemctl start openstack-ironic-api openstack-ironic-conductor


Configure the Bare Metal service
================================

The Bare Metal service is configured via its configuration file. This file
is typically located at ``/etc/ironic/ironic.conf``.

Although some configuration options are mentioned here, it is recommended that
you review all the `available options <https://git.openstack.org/cgit/openstack/ironic/tree/etc/ironic/ironic.conf.sample>`_
so that the Bare Metal service is configured for your needs.

It is possible to set up an ironic-api and an ironic-conductor services on the
same host or different hosts. Users also can add new ironic-conductor hosts
to deal with an increasing number of bare metal nodes. But the additional ironic-conductor
services should be at the same version as that of existing ironic-conductor services.

Configuring ironic-api service
------------------------------

#. The Bare Metal service stores information in a database. This guide uses the
   MySQL database that is used by other OpenStack services.

   Configure the location of the database via the ``connection`` option. In the
   following, replace IRONIC_DBPASSWORD with the password of your ``ironic``
   user, and replace DB_IP with the IP address where the DB server is located::

    [database]
    ...
    # The SQLAlchemy connection string used to connect to the
    # database (string value)
    connection = mysql+pymysql://ironic:IRONIC_DBPASSWORD@DB_IP/ironic?charset=utf8

#. Configure the ironic-api service to use the RabbitMQ message broker by
   setting one or more of these options. Replace RABBIT_HOST with the
   address of the RabbitMQ server::

    [DEFAULT]
    ...
    # The messaging driver to use, defaults to rabbit. Other
    # drivers include qpid and zmq. (string value)
    #rpc_backend=rabbit

    [oslo_messaging_rabbit]
    ...
    # The RabbitMQ broker address where a single node is used
    # (string value)
    rabbit_host=RABBIT_HOST

    # The RabbitMQ userid (string value)
    #rabbit_userid=guest

    # The RabbitMQ password (string value)
    #rabbit_password=guest

#. Configure the ironic-api service to use these credentials with the Identity
   service. Replace IDENTITY_IP with the IP of the Identity server, and
   replace IRONIC_PASSWORD with the password you chose for the ``ironic``
   user in the Identity service::

    [DEFAULT]
    ...
    # Authentication strategy used by ironic-api: one of
    # "keystone" or "noauth". "noauth" should not be used in a
    # production environment because all authentication will be
    # disabled. (string value)
    #auth_strategy=keystone

    [keystone_authtoken]
    ...
    # Complete public Identity API endpoint (string value)
    auth_uri=http://IDENTITY_IP:5000/

    # Complete admin Identity API endpoint. This should specify
    # the unversioned root endpoint e.g. https://localhost:35357/
    # (string value)
    identity_uri=http://IDENTITY_IP:35357/

    # Service username. (string value)
    admin_user=ironic

    # Service account password. (string value)
    admin_password=IRONIC_PASSWORD

    # Service tenant name. (string value)
    admin_tenant_name=service

#. Create the Bare Metal service database tables::

    ironic-dbsync --config-file /etc/ironic/ironic.conf create_schema

#. Restart the ironic-api service::

    Fedora/RHEL7/CentOS7:
      sudo systemctl restart openstack-ironic-api

    Ubuntu:
      sudo service ironic-api restart


Configuring ironic-conductor service
------------------------------------

#. Replace HOST_IP with IP of the conductor host, and replace DRIVERS with a
   comma-separated list of drivers you chose for the conductor service as
   follows::

    [DEFAULT]
    ...
    # IP address of this host. If unset, will determine the IP
    # programmatically. If unable to do so, will use "127.0.0.1".
    # (string value)
    my_ip = HOST_IP

    # Specify the list of drivers to load during service
    # initialization. Missing drivers, or drivers which fail to
    # initialize, will prevent the conductor service from
    # starting. The option default is a recommended set of
    # production-oriented drivers. A complete list of drivers
    # present on your system may be found by enumerating the
    # "ironic.drivers" entrypoint. An example may be found in the
    # developer documentation online. (list value)
    enabled_drivers=DRIVERS

   .. note::
      If a conductor host has multiple IPs, ``my_ip`` should
      be set to the IP which is on the same network as the bare metal nodes.

#. Configure the ironic-api service URL. Replace IRONIC_API_IP with IP of
   ironic-api service as follows::

    [conductor]
    ...
    # URL of Ironic API service. If not set ironic can get the
    # current value from the keystone service catalog. (string
    # value)
    api_url=http://IRONIC_API_IP:6385

#. Configure the location of the database. Ironic-conductor should use the same
   configuration as ironic-api. Replace IRONIC_DBPASSWORD with the password of
   your ``ironic`` user, and replace DB_IP with the IP address where the DB server
   is located::

    [database]
    ...
    # The SQLAlchemy connection string to use to connect to the
    # database. (string value)
    connection = mysql+pymysql://ironic:IRONIC_DBPASSWORD@DB_IP/ironic?charset=utf8

#. Configure the ironic-conductor service to use the RabbitMQ message broker by
   setting one or more of these options. Ironic-conductor should use the same
   configuration as ironic-api. Replace RABBIT_HOST with the address of the RabbitMQ
   server::

    [DEFAULT]
    ...
    # The messaging driver to use, defaults to rabbit. Other
    # drivers include qpid and zmq. (string value)
    #rpc_backend=rabbit

    [oslo_messaging_rabbit]
    ...
    # The RabbitMQ broker address where a single node is used.
    # (string value)
    rabbit_host=RABBIT_HOST

    # The RabbitMQ userid. (string value)
    #rabbit_userid=guest

    # The RabbitMQ password. (string value)
    #rabbit_password=guest

#. Configure the ironic-conductor service so that it can communicate with the
   Image service. Replace GLANCE_IP with the hostname or IP address of
   the Image service::

    [glance]
    ...
    # Default glance hostname or IP address. (string value)
    glance_host=GLANCE_IP

   .. note::
      Swift backend for the Image service should be installed and configured
      for ``agent_*`` drivers. Starting with Mitaka the Bare Metal service also
      supports Ceph Object Gateway (RADOS Gateway) as the Image service's backend
      (:ref:`radosgw support`).

#. Set the URL (replace NEUTRON_IP) for connecting to the Networking service,
   to be the Networking service endpoint::

    [neutron]
    ...
    # URL for connecting to neutron. (string value)
    url=http://NEUTRON_IP:9696

   To configure the network for ironic-conductor service to perform node cleaning, see
   `CleaningNetworkSetup`_.

#. Configure the ironic-conductor service to use these credentials with the Identity
   service. Ironic-conductor should use the same configuration as ironic-api.
   Replace IDENTITY_IP with the IP of the Identity server, and replace IRONIC_PASSWORD
   with the password you chose for the ``ironic`` user in the Identity service::

    [keystone_authtoken]
    ...
    # Complete public Identity API endpoint (string value)
    auth_uri=http://IDENTITY_IP:5000/

    # Complete admin Identity API endpoint. This should specify
    # the unversioned root endpoint e.g. https://localhost:35357/
    # (string value)
    identity_uri=http://IDENTITY_IP:35357/

    # Service username. (string value)
    admin_user=ironic

    # Service account password. (string value)
    admin_password=IRONIC_PASSWORD

    # Service tenant name. (string value)
    admin_tenant_name=service

#. Make sure that ``qemu-img`` and ``iscsiadm`` (in the case of using iscsi-deploy driver)
   binaries are installed and prepare the host system as described at
   `Setup the drivers for the Bare Metal service`_

#. Restart the ironic-conductor service::

    Fedora/RHEL7/CentOS7:
      sudo systemctl restart openstack-ironic-conductor

    Ubuntu:
      sudo service ironic-conductor restart


Configuring ironic-api behind mod_wsgi
--------------------------------------

Bare Metal service comes with an example file for configuring the
``ironic-api`` service to run behind Apache with mod_wsgi.

1. Install the apache service::

    Fedora 21/RHEL7/CentOS7:
      sudo yum install httpd

    Fedora 22 (or higher):
      sudo dnf install httpd

    Debian/Ubuntu:
      apt-get install apache2


2. Copy the ``etc/apache2/ironic`` file under the apache sites::

    Fedora/RHEL7/CentOS7:
      sudo cp etc/apache2/ironic /etc/httpd/conf.d/ironic.conf

    Debian/Ubuntu:
      sudo cp etc/apache2/ironic /etc/apache2/sites-available/ironic.conf


3. Edit the recently copied ``<apache-configuration-dir>/ironic.conf``:

  - Modify the ``WSGIDaemonProcess``, ``APACHE_RUN_USER`` and
    ``APACHE_RUN_GROUP`` directives to set the user and group values to
    an appropriate user on your server.

  - Modify the ``WSGIScriptAlias`` directive to point to the
    *ironic/api/app.wsgi* script.

  - Modify the ``Directory`` directive to set the path to the Ironic API code.


4. Enable the apache ``ironic`` in site and reload::

    Fedora/RHEL7/CentOS7:
      sudo systemctl reload httpd

    Debian/Ubuntu:
      sudo a2ensite ironic
      sudo service apache2 reload


.. note::
   The file ironic/api/app.wsgi is installed with the rest of the Bare Metal
   service application code, and should not need to be modified.


Configure Compute to use the Bare Metal service
===============================================

The Compute service needs to be configured to use the Bare Metal service's
driver.  The configuration file for the Compute service is typically located at
``/etc/nova/nova.conf``. *This configuration file must be modified on the
Compute service's controller nodes and compute nodes.*

1. Change these configuration options in the ``default`` section, as follows::

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
    #scheduler_host_manager=nova.scheduler.host_manager.HostManager
    scheduler_host_manager=nova.scheduler.ironic_host_manager.IronicHostManager

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

    # Full class name for the Manager for compute (string value)
    #compute_manager=nova.compute.manager.ComputeManager
    compute_manager=ironic.nova.compute.manager.ClusteredComputeManager

    # Flag to decide whether to use baremetal_scheduler_default_filters or not.
    # (boolean value)
    #scheduler_use_baremetal_filters=False
    scheduler_use_baremetal_filters=True

    # Determines if the Scheduler tracks changes to instances to help with
    # its filtering decisions (boolean value)
    #scheduler_tracks_instance_changes=True
    scheduler_tracks_instance_changes=False

2. Change these configuration options in the ``ironic`` section.
   Replace:

   - IRONIC_PASSWORD with the password you chose for the ``ironic``
     user in the Identity Service
   - IRONIC_NODE with the hostname or IP address of the ironic-api node
   - IDENTITY_IP with the IP of the Identity server

  ::

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

3. On the Compute service's controller nodes, restart the ``nova-scheduler`` process::

    Fedora/RHEL7/CentOS7:
      sudo systemctl restart openstack-nova-scheduler

    Ubuntu:
      sudo service nova-scheduler restart

4. On the Compute service's compute nodes, restart the ``nova-compute`` process::

    Fedora/RHEL7/CentOS7:
      sudo systemctl restart openstack-nova-compute

    Ubuntu:
      sudo service nova-compute restart

.. _NeutronFlatNetworking:

Configure Networking to communicate with the bare metal server
==============================================================

You need to configure Networking so that the bare metal server can communicate
with the Networking service for DHCP, PXE boot and other requirements.
This section covers configuring Networking for a single flat
network for bare metal provisioning.

You will also need to provide Bare Metal service with the MAC address(es) of
each node that it is provisioning; Bare Metal service in turn will pass this
information to Networking service for DHCP and PXE boot configuration.
An example of this is shown in the `Enrollment`_ section.

#. Edit ``/etc/neutron/plugins/ml2/ml2_conf.ini`` and modify these::

    [ml2]
    type_drivers = flat
    tenant_network_types = flat
    mechanism_drivers = openvswitch

    [ml2_type_flat]
    flat_networks = physnet1

    [ml2_type_vlan]
    network_vlan_ranges = physnet1

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

#. Add the integration bridge to Open vSwitch::

    ovs-vsctl add-br br-int

#. Create the br-eth2 network bridge to handle communication between the
   OpenStack services (and the Bare Metal services) and the bare metal nodes
   using eth2.
   Replace eth2 with the interface on the network node which you are
   using to connect to the Bare Metal service::

    ovs-vsctl add-br br-eth2
    ovs-vsctl add-port br-eth2 eth2

#. Restart the Open vSwitch agent::

    service neutron-plugin-openvswitch-agent restart

#. On restarting the Networking service Open vSwitch agent, the veth pair
   between the bridges br-int and br-eth2 is automatically created.

   Your Open vSwitch bridges should look something like this after
   following the above steps::

    ovs-vsctl show

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
   instances::

    neutron net-create --tenant-id $TENANT_ID sharednet1 --shared \
    --provider:network_type flat --provider:physical_network physnet1

#. Create the subnet on the newly created network::

    neutron subnet-create sharednet1 $NETWORK_CIDR --name $SUBNET_NAME \
    --ip-version=4 --gateway=$GATEWAY_IP --allocation-pool \
    start=$START_IP,end=$END_IP --enable-dhcp

.. _CleaningNetworkSetup:

Configure the Bare Metal service for cleaning
=============================================

#. If you configure Bare Metal service to use :ref:`cleaning` (which is enabled by
   default), you will need to set the ``cleaning_network_uuid`` configuration
   option. Note the network UUID (the `id` field) of the network you created in
   :ref:`NeutronFlatNetworking` or another network you created for cleaning::

    neutron net-list

#. Configure the cleaning network UUID via the ``cleaning_network_uuid``
   option in the Bare Metal service configuration file (/etc/ironic/ironic.conf).
   In the following, replace NETWORK_UUID with the UUID you noted in the
   previous step::

    [neutron]
    ...

    # UUID of the network to create Neutron ports on, when booting
    # to a ramdisk for cleaning using Neutron DHCP. (string value)
    #cleaning_network_uuid=<None>
    cleaning_network_uuid = NETWORK_UUID

#. Restart the Bare Metal service's ironic-conductor::

    Fedora/RHEL7/CentOS7:
      sudo systemctl restart openstack-ironic-conductor

    Ubuntu:
      sudo service ironic-conductor restart

.. _ImageRequirement:

Image requirements
==================

Bare Metal provisioning requires two sets of images: the deploy images
and the user images. The deploy images are used by the Bare Metal service
to prepare the bare metal server for actual OS deployment. Whereas the
user images are installed on the bare metal server to be used by the
end user. Below are the steps to create the required images and add
them to the Image service:

1. The `disk-image-builder`_ can be used to create images required for
   deployment and the actual OS which the user is going to run.

.. _disk-image-builder: https://github.com/openstack/diskimage-builder

   *Note:* `tripleo-incubator`_ provides a `script`_ to install all the
   dependencies for the disk-image-builder.

.. _tripleo-incubator: https://github.com/openstack/tripleo-incubator

.. _script: https://github.com/openstack/tripleo-incubator/blob/master/scripts/install-dependencies

   - Install diskimage-builder package (use virtualenv, if you don't
     want to install anything globally)::

       sudo pip install diskimage-builder

   - Build the image your users will run (Ubuntu image has been taken as
     an example)::

       Partition images:
           disk-image-create ubuntu baremetal dhcp-all-interfaces grub2 -o my-image

       Whole disk images:
           disk-image-create ubuntu vm dhcp-all-interfaces -o my-image

     The partition image command creates *my-image.qcow2*, *my-image.vmlinuz* and
     *my-image.initrd* files. The *grub2* element in the partition image creation
     command is only needed if local boot will be used to deploy *my-image.qcow2*,
     otherwise the images *my-image.vmlinuz* and *my-image.initrd* will be used for
     PXE booting after deploying the bare metal with *my-image.qcow2*.

     If you want to use Fedora image, replace *ubuntu* with *fedora* in the chosen
     command.

   - To build the deploy image take a look at the `Building or
     downloading a deploy ramdisk image`_ section.

2. Add the user images to the Image service

   Load all the images created in the below steps into the Image service,
   and note the image UUIDs in the Image service for each one as it is
   generated.

   - Add the kernel and ramdisk images to the Image service::

        glance image-create --name my-kernel --visibility public \
        --disk-format aki --container-format aki  < my-image.vmlinuz

     Store the image uuid obtained from the above step as
     *$MY_VMLINUZ_UUID*.

     ::

        glance image-create --name my-image.initrd --visibility public \
        --disk-format ari --container-format ari  < my-image.initrd

     Store the image UUID obtained from the above step as
     *$MY_INITRD_UUID*.

   - Add the *my-image* to the Image service which is going to be the OS
     that the user is going to run. Also associate the above created
     images with this OS image. These two operations can be done by
     executing the following command::

        glance image-create --name my-image --visibility public \
        --disk-format qcow2 --container-format bare --property \
        kernel_id=$MY_VMLINUZ_UUID --property \
        ramdisk_id=$MY_INITRD_UUID < my-image.qcow2

   - *Note:* To deploy a whole disk image, a kernel_id and a ramdisk_id
     shouldn't be associated with the image. An example is as follows::

         glance image-create --name my-whole-disk-image --visibility public \
         --disk-format qcow2 \
         --container-format bare < my-whole-disk-image.qcow2

3. Add the deploy images to the Image service

   Add the *my-deploy-ramdisk.kernel* and
   *my-deploy-ramdisk.initramfs* images to the Image service::

        glance image-create --name deploy-vmlinuz --visibility public \
        --disk-format aki --container-format aki < my-deploy-ramdisk.kernel

   Store the image UUID obtained from the above step as
   *$DEPLOY_VMLINUZ_UUID*.

   ::

        glance image-create --name deploy-initrd --visibility public \
        --disk-format ari --container-format ari < my-deploy-ramdisk.initramfs

   Store the image UUID obtained from the above step as
   *$DEPLOY_INITRD_UUID*.

Flavor creation
===============

You'll need to create a special bare metal flavor in the Compute service.
The flavor is mapped to the bare metal node through the hardware specifications.

#. Change these to match your hardware::

    RAM_MB=1024
    CPU=2
    DISK_GB=100
    ARCH={i686|x86_64}

#. Create the bare metal flavor by executing the following command::

    nova flavor-create my-baremetal-flavor auto $RAM_MB $DISK_GB $CPU

   *Note: You can replace auto with your own flavor id.*

#. Set the architecture as extra_specs information of the flavor. This
   will be used to match against the properties of bare metal nodes::

    nova flavor-key my-baremetal-flavor set cpu_arch=$ARCH

#. Associate the deploy ramdisk and kernel images with the ironic node::

    ironic node-update $NODE_UUID add \
    driver_info/deploy_kernel=$DEPLOY_VMLINUZ_UUID \
    driver_info/deploy_ramdisk=$DEPLOY_INITRD_UUID


Setup the drivers for the Bare Metal service
============================================

PXE setup
---------

If you will be using PXE, it needs to be set up on the Bare Metal service
node(s) where ``ironic-conductor`` is running.

#. Make sure the tftp root directory exist and can be written to by the
   user the ``ironic-conductor`` is running as. For example::

    sudo mkdir -p /tftpboot
    sudo chown -R ironic /tftpboot

#. Install tftp server and the syslinux package with the PXE boot images::

    Ubuntu: (Up to and including 14.04)
        sudo apt-get install tftpd-hpa syslinux-common syslinux

    Ubuntu: (14.10 and after)
        sudo apt-get install tftpd-hpa syslinux-common pxelinux

    Fedora 21/RHEL7/CentOS7:
        sudo yum install tftp-server syslinux-tftpboot

    Fedora 22 or higher:
         sudo dnf install tftp-server syslinux-tftpboot

#. Setup tftp server to serve ``/tftpboot``.

#. Copy the PXE image to ``/tftpboot``. The PXE image might be found at [1]_::

    Ubuntu (Up to and including 14.04):
        sudo cp /usr/lib/syslinux/pxelinux.0 /tftpboot

    Ubuntu (14.10 and after):
        sudo cp /usr/lib/PXELINUX/pxelinux.0 /tftpboot

#. If whole disk images need to be deployed via PXE-netboot, copy the
   chain.c32 image to ``/tftpboot`` to support it. The chain.c32 image
   might be found at::

    Ubuntu (Up to and including 14.04):
        sudo cp /usr/lib/syslinux/chain.c32 /tftpboot

    Ubuntu (14.10 and after):
        sudo cp /usr/lib/syslinux/modules/bios/chain.c32 /tftpboot

    Fedora/RHEL7/CentOS7:
        sudo cp /boot/extlinux/chain.c32 /tftpboot

#. If the version of syslinux is **greater than** 4 we also need to make sure
   that we copy the library modules into the ``/tftpboot`` directory [2]_
   [1]_::

    Ubuntu:
        sudo cp /usr/lib/syslinux/modules/*/ldlinux.* /tftpboot

#. Create a map file in the tftp boot directory (``/tftpboot``)::

    echo 're ^(/tftpboot/) /tftpboot/\2' > /tftpboot/map-file
    echo 're ^/tftpboot/ /tftpboot/' >> /tftpboot/map-file
    echo 're ^(^/) /tftpboot/\1' >> /tftpboot/map-file
    echo 're ^([^/]) /tftpboot/\1' >> /tftpboot/map-file

#. Enable tftp map file, modify ``/etc/xinetd.d/tftp`` as below and restart xinetd
   service::

    server_args = -v -v -v -v -v --map-file /tftpboot/map-file /tftpboot

.. [1] On **Fedora/RHEL** the ``syslinux-tftpboot`` package already install
       the library modules and PXE image at ``/tftpboot``. If the TFTP server
       is configured to listen to a different directory you should copy the
       contents of ``/tftpboot`` to the configured directory
.. [2] http://www.syslinux.org/wiki/index.php/Library_modules


PXE UEFI setup
--------------

If you want to deploy on a UEFI supported bare metal, perform these additional
steps on the ironic conductor node to configure the PXE UEFI environment.

#. Download and untar the elilo bootloader version >= 3.16 from
   http://sourceforge.net/projects/elilo/::

    sudo tar zxvf elilo-3.16-all.tar.gz

#. Copy the elilo boot loader image to ``/tftpboot`` directory::

    sudo cp ./elilo-3.16-x86_64.efi /tftpboot/elilo.efi

#. Grub2 is an alternate UEFI bootloader supported in Bare Metal service.
   Install grub2 and shim packages::

    Ubuntu: (14.04LTS and later)
        sudo apt-get install grub-efi-amd64-signed shim-signed

    Fedora 21/RHEL7/CentOS7:
        sudo yum install grub2-efi shim

    Fedora 22 or higher:
        sudo dnf install grub2-efi shim

#. Copy grub and shim boot loader images to ``/tftpboot`` directory::

    Ubuntu: (14.04LTS and later)
        sudo cp /usr/lib/shim/shim.efi.signed /tftpboot/bootx64.efi
        sudo cp /usr/lib/grub/x86_64-efi-signed/grubnetx64.efi.signed  \
        /tftpboot/grubx64.efi

    Fedora: (21 and later)
        sudo cp /boot/efi/EFI/fedora/shim.efi /tftpboot/bootx64.efi
        sudo cp /boot/efi/EFI/fedora/grubx64.efi /tftpboot/grubx64.efi

    CentOS: (7 and later)
        sudo cp /boot/efi/EFI/centos/shim.efi /tftpboot/bootx64.efi
        sudo cp /boot/efi/EFI/centos/grubx64.efi /tftpboot/grubx64.efi

#. Create master grub.cfg::

    Ubuntu: Create grub.cfg under ``/tftpboot/grub`` directory.
        GRUB_DIR=/tftpboot/grub

    Fedora: Create grub.cfg under ``/tftpboot/EFI/fedora`` directory.
         GRUB_DIR=/tftpboot/EFI/fedora

    CentOS: Create grub.cfg under ``/tftpboot/EFI/centos`` directory.
        GRUB_DIR=/tftpboot/EFI/centos

    Create directory GRUB_DIR
      sudo mkdir -p $GRUB_DIR

   This file is used to redirect grub to baremetal node specific config file.
   It redirects it to specific grub config file based on DHCP IP assigned to
   baremetal node.

   .. literalinclude:: ../../../ironic/drivers/modules/master_grub_cfg.txt

   Change the permission of grub.cfg::

    sudo chmod 644 $GRUB_DIR/grub.cfg

#. Update bootfile and template file configuration parameters for UEFI PXE boot
   in the Bare Metal Service's configuration file (/etc/ironic/ironic.conf)::

    [pxe]

    # Bootfile DHCP parameter for UEFI boot mode. (string value)
    uefi_pxe_bootfile_name=bootx64.efi

    # Template file for PXE configuration for UEFI boot loader.
    # (string value)
    uefi_pxe_config_template=$pybasedir/drivers/modules/pxe_grub_config.template

#. Update the bare metal node with ``boot_mode`` capability in node's properties
   field::

    ironic node-update <node-uuid> add properties/capabilities='boot_mode:uefi'

#. Make sure that bare metal node is configured to boot in UEFI boot mode and
   boot device is set to network/pxe.

   NOTE: ``pxe_ilo`` driver supports automatic setting of UEFI boot mode and
   boot device on the bare metal node. So this step is not required for
   ``pxe_ilo`` driver.

For more information on configuring boot modes, refer boot_mode_support_.


iPXE setup
----------

An alternative to PXE boot, iPXE was introduced in the Juno release
(2014.2.0) of Bare Metal service.

If you will be using iPXE to boot instead of PXE, iPXE needs to be set up
on the Bare Metal service node(s) where ``ironic-conductor`` is running.

#. Make sure these directories exist and can be written to by the user
   the ``ironic-conductor`` is running as. For example::

    sudo mkdir -p /tftpboot
    sudo mkdir -p /httpboot
    sudo chown -R ironic /tftpboot
    sudo chown -R ironic /httpboot

#. Create a map file in the tftp boot directory (``/tftpboot``)::

    echo 'r ^([^/]) /tftpboot/\1' > /tftpboot/map-file
    echo 'r ^(/tftpboot/) /tftpboot/\2' >> /tftpboot/map-file

#. Set up TFTP and HTTP servers.

   These servers should be running and configured to use the local
   /tftpboot and /httpboot directories respectively, as their root
   directories. (Setting up these servers is outside the scope of this
   install guide.)

   These root directories need to be mounted locally to the
   ``ironic-conductor`` services, so that the services can access them.

   The Bare Metal service's configuration file (/etc/ironic/ironic.conf)
   should be edited accordingly to specify the TFTP and HTTP root
   directories and server addresses. For example::

    [pxe]

    # Ironic compute node's tftp root path. (string value)
    tftp_root=/tftpboot

    # IP address of Ironic compute node's tftp server. (string
    # value)
    tftp_server=192.168.0.2

    [deploy]
    # Ironic compute node's http root path. (string value)
    http_root=/httpboot

    # Ironic compute node's HTTP server URL. Example:
    # http://192.1.2.3:8080 (string value)
    http_url=http://192.168.0.2:8080

#. Install the iPXE package with the boot images::

    Ubuntu:
        apt-get install ipxe

    Fedora 21/RHEL7/CentOS7:
        yum install ipxe-bootimgs

    Fedora 22 or higher:
        dnf install ipxe-bootimgs

#. Copy the iPXE boot image (``undionly.kpxe`` for **BIOS** and
   ``ipxe.efi`` for **UEFI**) to ``/tftpboot``. The binary might
   be found at::

    Ubuntu:
        cp /usr/lib/ipxe/{undionly.kpxe,ipxe.efi} /tftpboot

    Fedora/RHEL7/CentOS7:
        cp /usr/share/ipxe/{undionly.kpxe,ipxe.efi} /tftpboot

   .. note::
      If the packaged version of the iPXE boot image doesn't work, you can
      download a prebuilt one from http://boot.ipxe.org or build one image
      from source, see http://ipxe.org/download for more information.

#. Enable/Configure iPXE in the Bare Metal Service's configuration file
   (/etc/ironic/ironic.conf)::

    [pxe]

    # Enable iPXE boot. (boolean value)
    ipxe_enabled=True

    # Neutron bootfile DHCP parameter. (string value)
    pxe_bootfile_name=undionly.kpxe

    # Bootfile DHCP parameter for UEFI boot mode. (string value)
    uefi_pxe_bootfile_name=ipxe.efi

    # Template file for PXE configuration. (string value)
    pxe_config_template=$pybasedir/drivers/modules/ipxe_config.template

    # Template file for PXE configuration for UEFI boot loader.
    # (string value)
    uefi_pxe_config_template=$pybasedir/drivers/modules/ipxe_config.template

#. Restart the ``ironic-conductor`` process::

    Fedora/RHEL7/CentOS7:
      sudo systemctl restart openstack-ironic-conductor

    Ubuntu:
      sudo service ironic-conductor restart


Networking service configuration
--------------------------------

DHCP requests from iPXE need to have a DHCP tag called ``ipxe``, in order
for the DHCP server to tell the client to get the boot.ipxe script via
HTTP. Otherwise, if the tag isn't there, the DHCP server will tell the
DHCP client to chainload the iPXE image (undionly.kpxe).
The Networking service needs to be configured to create this DHCP tag,
since it isn't created by default.

#. Create a custom ``dnsmasq.conf`` file with a setting for the ipxe tag. For
   example, create the file ``/etc/dnsmasq-ironic.conf`` with the content::

    # Create the "ipxe" tag if request comes from iPXE user class
    dhcp-userclass=set:ipxe,iPXE

    # Alternatively, create the "ipxe" tag if request comes from DHCP option 175
    # dhcp-match=set:ipxe,175

#. In the Networking service DHCP Agent configuration file (typically located at
   /etc/neutron/dhcp_agent.ini), set the custom ``/etc/dnsmasq-ironic.conf``
   file as the dnsmasq configuration file::

    [DEFAULT]
    dnsmasq_config_file = /etc/dnsmasq-ironic.conf


#. Restart the ``neutron-dhcp-agent`` process::

    service neutron-dhcp-agent restart


IPMI support
------------

If using the IPMITool driver, the ``ipmitool`` command must be present on the
service node(s) where ``ironic-conductor`` is running. On most distros, this
is provided as part of the ``ipmitool`` package. Source code is available at
http://ipmitool.sourceforge.net/

Note that certain distros, notably Mac OS X and SLES, install ``openipmi``
instead of ``ipmitool`` by default. THIS DRIVER IS NOT COMPATIBLE WITH
``openipmi`` AS IT RELIES ON ERROR HANDLING OPTIONS NOT PROVIDED BY THIS TOOL.

Check that you can connect to and authenticate with the IPMI
controller in your bare metal server by using ``ipmitool``::

    ipmitool -I lanplus -H <ip-address> -U <username> -P <password> chassis power status

<ip-address> = The IP of the IPMI controller you want to access

*Note:*

#. This is not the bare metal node's main IP. The IPMI controller
   should have its own unique IP.

#. In case the above command doesn't return the power status of the
   bare metal server, check for these:

   - ``ipmitool`` is installed.
   - The IPMI controller on your bare metal server is turned on.
   - The IPMI controller credentials passed in the command are right.
   - The conductor node has a route to the IPMI controller. This can be
     checked by just pinging the IPMI controller IP from the conductor
     node.

.. note::
   If there are slow or unresponsive BMCs in the environment, the retry_timeout
   configuration option in the [ipmi] section may need to be lowered. The
   default is fairly conservative, as setting this timeout too low can cause
   older BMCs to crash and require a hard-reset.

Bare Metal service supports sending IPMI sensor data to Telemetry with pxe_ipmitool,
pxe_ipminative, agent_ipmitool, agent_pyghmi, agent_ilo, iscsi_ilo, pxe_ilo,
and with pxe_irmc driver starting from Kilo release. By default, support for
sending IPMI sensor data to Telemetry is disabled. If you want to enable it,
you should make the following two changes in ``ironic.conf``:

* ``notification_driver = messaging`` in the ``DEFAULT`` section
* ``send_sensor_data = true`` in the ``conductor`` section

If you want to customize the sensor types which will be sent to Telemetry,
change the ``send_sensor_data_types`` option. For example, the below
settings will send temperature, fan, voltage and these three sensor types
of data to Telemetry:

* send_sensor_data_types=Temperature,Fan,Voltage

If we use default value 'All' for all the sensor types which are supported by
Telemetry, they are:

* Temperature, Fan, Voltage, Current


Configure node web console
--------------------------

The web console can be configured in Bare Metal service in the following way:

* Install shellinabox in ironic conductor node. For RHEL/CentOS, shellinabox package
  is not present in base repositories, user must enable EPEL repository, you can find
  more from `FedoraProject page`_.

  Installation example::

    Ubuntu:
        sudo apt-get install shellinabox

    Fedora 21/RHEL7/CentOS7:
        sudo yum install shellinabox

    Fedora 22 or higher:
         sudo dnf install shellinabox

  You can find more about shellinabox on the `shellinabox page`_.

  You can optionally use the SSL certificate in shellinabox. If you want to use the SSL
  certificate in shellinabox, you should install openssl and generate the SSL certificate.

  1. Install openssl, for example::

        Ubuntu:
             sudo apt-get install openssl

        Fedora 21/RHEL7/CentOS7:
             sudo yum install openssl

        Fedora 22 or higher:
             sudo dnf install openssl

  2. Generate the SSL certificate, here is an example, you can find more about openssl on
     the `openssl page`_::

        cd /tmp/ca
        openssl genrsa -des3 -out my.key 1024
        openssl req -new -key my.key  -out my.csr
        cp my.key my.key.org
        openssl rsa -in my.key.org -out my.key
        openssl x509 -req -days 3650 -in my.csr -signkey my.key -out my.crt
        cat my.crt my.key > certificate.pem

* Customize the console section in the Bare Metal service configuration
  file (/etc/ironic/ironic.conf), if you want to use SSL certificate in
  shellinabox, you should specify ``terminal_cert_dir``.
  for example::

   [console]

   #
   # Options defined in ironic.drivers.modules.console_utils
   #

   # Path to serial console terminal program (string value)
   #terminal=shellinaboxd

   # Directory containing the terminal SSL cert(PEM) for serial
   # console access (string value)
   terminal_cert_dir=/tmp/ca

   # Directory for holding terminal pid files. If not specified,
   # the temporary directory will be used. (string value)
   #terminal_pid_dir=<None>

   # Time interval (in seconds) for checking the status of
   # console subprocess. (integer value)
   #subprocess_checking_interval=1

   # Time (in seconds) to wait for the console subprocess to
   # start. (integer value)
   #subprocess_timeout=10

* Append console parameters for bare metal PXE boot in the Bare Metal service
  configuration file (/etc/ironic/ironic.conf), including right serial port
  terminal and serial speed, serial speed should be same serial configuration
  with BIOS settings, so that os boot process can be seen in web console,
  for example::

   pxe_* driver:

        [pxe]

        #Additional append parameters for bare metal PXE boot. (string value)
        pxe_append_params = nofb nomodeset vga=normal console=tty0 console=ttyS0,115200n8

   agent_* driver:

        [agent]

        #Additional append parameters for bare metal PXE boot. (string value)
        agent_pxe_append_params = nofb nomodeset vga=normal console=tty0 console=ttyS0,115200n8

* Configure node web console.

  Enable the web console, for example::

   ironic node-update <node-uuid> add driver_info/<terminal_port>=<customized_port>
   ironic node-set-console-mode <node-uuid> true

  Check whether the console is enabled, for example::

   ironic node-validate <node-uuid>

  Disable the web console, for example::

   ironic node-set-console-mode <node-uuid> false
   ironic node-update <node-uuid> remove driver_info/<terminal_port>

  The ``<terminal_port>`` is driver dependent. The actual name of this field can be
  checked in driver properties, for example::

   ironic driver-properties <driver>

  For ``*_ipmitool`` and ``*_ipminative`` drivers, this option is ``ipmi_terminal_port``.
  For ``seamicro`` driver, this option is ``seamicro_terminal_port``. Give a customized port
  number to ``<customized_port>``, for example ``8023``, this customized port is used in
  web console url.

* Get web console information::

   ironic node-get-console <node-uuid>
   +-----------------+----------------------------------------------------------------------+
   | Property        | Value                                                                |
   +-----------------+----------------------------------------------------------------------+
   | console_enabled | True                                                                 |
   | console_info    | {u'url': u'http://<url>:<customized_port>', u'type': u'shellinabox'} |
   +-----------------+----------------------------------------------------------------------+

  You can open web console using above ``url`` through web browser. If ``console_enabled`` is
  ``false``, ``console_info`` is ``None``, web console is disabled. If you want to launch web
  console, refer to ``Enable web console`` part.

.. _`shellinabox page`: https://code.google.com/p/shellinabox/
.. _`openssl page`: https://www.openssl.org/
.. _`FedoraProject page`: https://fedoraproject.org/wiki/Infrastructure/Mirroring

.. _boot_mode_support:

Boot mode support
-----------------

The following drivers support setting of boot mode (Legacy BIOS or UEFI).

* ``pxe_ipmitool``

The boot modes can be configured in Bare Metal service in the following way:

* When no boot mode setting is provided, these drivers default the boot_mode
  to Legacy BIOS.

* Only one boot mode (either ``uefi`` or ``bios``) can be configured for
  the node.

* If the operator wants a node to boot always in ``uefi`` mode or ``bios``
  mode, then they may use ``capabilities`` parameter within ``properties``
  field of an bare metal node.  The operator must manually set the appropriate
  boot mode on the bare metal node.

  To configure a node in ``uefi`` mode, then set ``capabilities`` as below::

    ironic node-update <node-uuid> add properties/capabilities='boot_mode:uefi'

  Nodes having ``boot_mode`` set to ``uefi`` may be requested by adding an
  ``extra_spec`` to the Compute service flavor::

    nova flavor-key ironic-test-3 set capabilities:boot_mode="uefi"
    nova boot --flavor ironic-test-3 --image test-image instance-1

  If ``capabilities`` is used in ``extra_spec`` as above, nova scheduler
  (``ComputeCapabilitiesFilter``) will match only bare metal nodes which have
  the ``boot_mode`` set appropriately in ``properties/capabilities``. It will
  filter out rest of the nodes.

  The above facility for matching in the Compute service can be used in
  heterogeneous environments where there is a mix of ``uefi`` and ``bios``
  machines, and operator wants to provide a choice to the user regarding
  boot modes. If the flavor doesn't contain ``boot_mode`` and ``boot_mode``
  is configured for bare metal nodes, then nova scheduler will consider all
  nodes and user may get either ``bios`` or ``uefi`` machine.

.. _choosing_the_disk_label:

Choosing the disk label
-----------------------

.. note::
   The term ``disk label`` is historically used in Ironic and was taken
   from `parted <https://www.gnu.org/software/parted>`_. Apparently
   everyone seems to have a different word for ``disk label`` - these
   are all the same thing: disk type, partition table, partition map
   and so on...

Ironic allows operators to choose which disk label they want their
bare metal node to be deployed with when Ironic is responsible for
partitioning the disk; therefore choosing the disk label does not apply
when the image being deployed is a ``whole disk image``.

There are some edge cases where someone may want to choose a specific
disk label for the images being deployed, including but not limited to:

* For machines in ``bios`` boot mode with disks larger than 2 terabytes
  it's recommended to use a ``gpt`` disk label. That's because
  a capacity beyond 2 terabytes is not addressable by using the
  MBR partitioning type. But, although GPT claims to be backward
  compatible with legacy BIOS systems `that's not always the case
  <http://www.rodsbooks.com/gdisk/bios.html>`_.

* Operators may want to force the partitioning to be always MBR (even
  if the machine is deployed with boot mode ``uefi``) to avoid breakage
  of applications and tools running on those instances.

The disk label can be configured in two ways; when Ironic is used with
the Compute service or in standalone mode. The following bullet points
and sections will describe both methods:

* When no disk label is provided Ironic will configure it according
  to the `boot mode <boot_mode_support_>`_; ``bios`` boot mode will use
  ``msdos`` and ``uefi`` boot mode will use ``gpt``.

* Only one disk label - either ``msdos`` or ``gpt`` - can be configured
  for the node.

When used with Compute service
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

When Ironic is used with the Compute service the disk label should be
set to node's ``properties/capabilities`` field and also to the flavor
which will request such capability, for example::

    ironic node-update <node-uuid> add properties/capabilities='disk_label:gpt'

As for the flavor::

    nova flavor-key baremetal set capabilities:disk_label="gpt"

When used in standalone mode
~~~~~~~~~~~~~~~~~~~~~~~~~~~~

When used without the Compute service, the disk label should be set
directly to the node's ``instance_info`` field, as below::

    ironic node-update <node-uuid> add instance_info/capabilities='{"disk_label": "gpt"}'


Local boot with partition images
================================

Starting with the Kilo release, Bare Metal service supports local boot with
partition images, meaning that after the deployment the node's subsequent
reboots won't happen via PXE or Virtual Media. Instead, it will boot from a
local boot loader installed on the disk.

It's important to note that in order for this to work the image being
deployed with Bare Metal serivce **must** contain ``grub2`` installed within it.

Enabling the local boot is different when Bare Metal service is used with
Compute service and without it.
The following sections will describe both methods.

.. note::
   The local boot feature is dependent upon a updated deploy ramdisk built
   with diskimage-builder_ **version >= 0.1.42** or ironic-python-agent_
   in the kilo-era.

Enabling local boot with Compute service
----------------------------------------

To enable local boot we need to set a capability on the bare metal node,
for example::

    ironic node-update <node-uuid> add properties/capabilities="boot_option:local"


Nodes having ``boot_option`` set to ``local`` may be requested by adding
an ``extra_spec`` to the Compute service flavor, for example::

    nova flavor-key baremetal set capabilities:boot_option="local"


.. note::
    If the node is configured to use ``UEFI``, Bare Metal service will create
    an ``EFI partition`` on the disk and switch the partition table format to
    ``gpt``. The ``EFI partition`` will be used later by the boot loader
    (which is installed from the deploy ramdisk).


Enabling local boot without Compute
-----------------------------------

Since adding ``capabilities`` to the node's properties is only used by
the nova scheduler to perform more advanced scheduling of instances,
we need a way to enable local boot when Compute is not present. To do that
we can simply specify the capability via the ``instance_info`` attribute
of the node, for example::

    ironic node-update <node-uuid> add instance_info/capabilities='{"boot_option": "local"}'


Enrollment
==========

After all the services have been properly configured, you should enroll your
hardware with the Bare Metal service, and confirm that the Compute service sees
the available hardware. The nodes will be visible to the Compute service once
they are in the ``available`` provision state.

.. note::
   After enrolling nodes with the Bare Metal service, the Compute service
   will not be immediately notified of the new resources. The Compute service's
   resource tracker syncs periodically, and so any changes made directly to the
   Bare Metal service's resources will become visible in the Compute service
   only after the next run of that periodic task.
   More information is in the `Troubleshooting`_ section below.

.. note::
   Any bare metal node that is visible to the Compute service may have a
   workload scheduled to it, if both the ``power`` and ``deploy`` interfaces
   pass the ``validate`` check.
   If you wish to exclude a node from the Compute service's scheduler, for
   instance so that you can perform maintenance on it, you can set the node to
   "maintenance" mode.
   For more information see the `Maintenance Mode`_ section below.

Enrollment process
------------------

This section describes the main steps to enroll a node and make it available
for provisioning. Some steps are shown separately for illustration purposes,
and may be combined if desired.

#. Create a node in the Bare Metal service. At a minimum, you must
   specify the driver name (for example, "pxe_ipmitool").
   This will return the node UUID along with other information
   about the node. The node's provision state will be ``available``. (The
   example assumes that the client is using the default API version.)::

    ironic node-create -d pxe_ipmitool
    +--------------+--------------------------------------+
    | Property     | Value                                |
    +--------------+--------------------------------------+
    | uuid         | dfc6189f-ad83-4261-9bda-b27258eb1987 |
    | driver_info  | {}                                   |
    | extra        | {}                                   |
    | driver       | pxe_ipmitool                         |
    | chassis_uuid |                                      |
    | properties   | {}                                   |
    | name         | None                                 |
    +--------------+--------------------------------------+

    ironic node-show dfc6189f-ad83-4261-9bda-b27258eb1987
    +------------------------+--------------------------------------+
    | Property               | Value                                |
    +------------------------+--------------------------------------+
    | target_power_state     | None                                 |
    | extra                  | {}                                   |
    | last_error             | None                                 |
    | maintenance_reason     | None                                 |
    | provision_state        | available                            |
    | uuid                   | dfc6189f-ad83-4261-9bda-b27258eb1987 |
    | console_enabled        | False                                |
    | target_provision_state | None                                 |
    | provision_updated_at   | None                                 |
    | maintenance            | False                                |
    | power_state            | None                                 |
    | driver                 | pxe_ipmitool                         |
    | properties             | {}                                   |
    | instance_uuid          | None                                 |
    | name                   | None                                 |
    | driver_info            | {}                                   |
    | ...                    | ...                                  |
    +------------------------+--------------------------------------+

   Beginning with the Kilo release a node may also be referred to by a logical
   name as well as its UUID. To utilize this new feature a name must be
   assigned to the node. This can be done when the node is created by
   adding the ``-n`` option to the ``node-create`` command or by updating an
   existing node with the ``node-update`` command. See `Logical Names`_ for
   examples.

   Beginning with the Liberty release, with API version 1.11 and above, a newly
   created node will have an initial provision state of ``enroll`` as opposed to
   ``available``. See `Enrolling a node`_ for more details.

#. Update the node ``driver_info`` so that Bare Metal service can manage the
   node. Different drivers may require different information about the node.
   You can determine this with the ``driver-properties`` command, as follows::

    ironic driver-properties pxe_ipmitool
    +----------------------+-------------------------------------------------------------------------------------------------------------+
    | Property             | Description                                                                                                 |
    +----------------------+-------------------------------------------------------------------------------------------------------------+
    | ipmi_address         | IP address or hostname of the node. Required.                                                               |
    | ipmi_password        | password. Optional.                                                                                         |
    | ipmi_username        | username; default is NULL user. Optional.                                                                   |
    | ...                  | ...                                                                                                         |
    | deploy_kernel        | UUID (from Glance) of the deployment kernel. Required.                                                      |
    | deploy_ramdisk       | UUID (from Glance) of the ramdisk that is mounted at boot time. Required.                                   |
    +----------------------+-------------------------------------------------------------------------------------------------------------+

    ironic node-update $NODE_UUID add \
    driver_info/ipmi_username=$USER \
    driver_info/ipmi_password=$PASS \
    driver_info/ipmi_address=$ADDRESS

   .. note::
      If IPMI is running on a port other than 623 (the default). The port must
      be added to ``driver_info`` by specifying the ``ipmi_port`` value.
      Example::

       ironic node-update $NODE_UUID add driver_info/ipmi_port=$PORT_NUMBER

      Note that you may also specify all ``driver_info`` parameters during
      ``node-create`` by passing the **-i** option multiple times.

#. Update the node's properties to match the bare metal flavor you created
   earlier::

    ironic node-update $NODE_UUID add \
    properties/cpus=$CPU \
    properties/memory_mb=$RAM_MB \
    properties/local_gb=$DISK_GB \
    properties/cpu_arch=$ARCH

   As above, these can also be specified at node creation by passing the **-p**
   option to ``node-create`` multiple times.

#. If you wish to perform more advanced scheduling of the instances based on
   hardware capabilities, you may add metadata to each node that will be
   exposed to the nova scheduler (see: `ComputeCapabilitiesFilter`_).  A full
   explanation of this is outside of the scope of this document. It can be done
   through the special ``capabilities`` member of node properties::

    ironic node-update $NODE_UUID add \
    properties/capabilities=key1:val1,key2:val2

#. As mentioned in the `Flavor Creation`_ section, if using the Kilo or later
   release of Bare Metal service, you should specify a deploy kernel and
   ramdisk which correspond to the node's driver, for example::

    ironic node-update $NODE_UUID add \
    driver_info/deploy_kernel=$DEPLOY_VMLINUZ_UUID \
    driver_info/deploy_ramdisk=$DEPLOY_INITRD_UUID

#. You must also inform Bare Metal service of the network interface cards which
   are part of the node by creating a port with each NIC's MAC address.
   These MAC addresses are passed to the Networking service during instance
   provisioning and used to configure the network appropriately::

    ironic port-create -n $NODE_UUID -a $MAC_ADDRESS

#. To check if Bare Metal service has the minimum information necessary for
   a node's driver to function, you may ``validate`` it::

    ironic node-validate $NODE_UUID

    +------------+--------+--------+
    | Interface  | Result | Reason |
    +------------+--------+--------+
    | console    | True   |        |
    | deploy     | True   |        |
    | management | True   |        |
    | power      | True   |        |
    +------------+--------+--------+

   If the node fails validation, each driver will return information as to why
   it failed::

    ironic node-validate $NODE_UUID

    +------------+--------+-------------------------------------------------------------------------------------------------------------------------------------+
    | Interface  | Result | Reason                                                                                                                              |
    +------------+--------+-------------------------------------------------------------------------------------------------------------------------------------+
    | console    | None   | not supported                                                                                                                       |
    | deploy     | False  | Cannot validate iSCSI deploy. Some parameters were missing in node's instance_info. Missing are: ['root_gb', 'image_source']        |
    | management | False  | Missing the following IPMI credentials in node's driver_info: ['ipmi_address'].                                                     |
    | power      | False  | Missing the following IPMI credentials in node's driver_info: ['ipmi_address'].                                                     |
    +------------+--------+-------------------------------------------------------------------------------------------------------------------------------------+

#. If using API version 1.11 or above, the node was created in the ``enroll``
   provision state. In order for the node to be available for deploying a
   workload (for example, by the Compute service), it needs to be in the
   ``available`` provision state. To do this, it must be moved into the
   ``manageable`` state and then moved into the ``available`` state. The
   `API version 1.11 and above`_ section describes the commands for this.

.. _ComputeCapabilitiesFilter: http://docs.openstack.org/developer/nova/devref/filter_scheduler.html?highlight=computecapabilitiesfilter


Enrolling a node
----------------
In the Liberty cycle, starting with API version 1.11, the Bare Metal service
added a new initial provision state of ``enroll`` to its state machine.

Existing automation tooling that use an API version lower than 1.11 are not
affected, since the initial provision state is still ``available``.
However, using API version 1.11 or above may break existing automation tooling
with respect to node creation.

The default API version used by (the most recent) python-ironicclient is 1.9.

The examples below set the API version for each command. To set the
API version for all commands, you can set the environment variable
``IRONIC_API_VERSION``.

API version 1.10 and below
~~~~~~~~~~~~~~~~~~~~~~~~~~

Below is an example of creating a node with API version 1.10. After creation,
the node will be in the ``available`` provision state.
Other API versions below 1.10 may be substituted in place of 1.10.

::

    ironic --ironic-api-version 1.10 node-create -d agent_ilo -n pre11

    +--------------+--------------------------------------+
    | Property     | Value                                |
    +--------------+--------------------------------------+
    | uuid         | cc4998a0-f726-4927-9473-0582458c6789 |
    | driver_info  | {}                                   |
    | extra        | {}                                   |
    | driver       | agent_ilo                            |
    | chassis_uuid |                                      |
    | properties   | {}                                   |
    | name         | pre11                                |
    +--------------+--------------------------------------+


    ironic --ironic-api-version 1.10 node-list

    +--------------------------------------+-------+---------------+-------------+--------------------+-------------+
    | UUID                                 | Name  | Instance UUID | Power State | Provisioning State | Maintenance |
    +--------------------------------------+-------+---------------+-------------+--------------------+-------------+
    | cc4998a0-f726-4927-9473-0582458c6789 | pre11 | None          | None        | available          | False       |
    +--------------------------------------+-------+---------------+-------------+--------------------+-------------+

API version 1.11 and above
~~~~~~~~~~~~~~~~~~~~~~~~~~

Beginning with API version 1.11, the initial provision state for newly created
nodes is ``enroll``. In the examples below, other API versions above 1.11 may be
substituted in place of 1.11.
::

    ironic --ironic-api-version 1.11 node-create -d agent_ilo -n post11

    +--------------+--------------------------------------+
    | Property     | Value                                |
    +--------------+--------------------------------------+
    | uuid         | 0eb013bb-1e4b-4f4c-94b5-2e7468242611 |
    | driver_info  | {}                                   |
    | extra        | {}                                   |
    | driver       | agent_ilo                            |
    | chassis_uuid |                                      |
    | properties   | {}                                   |
    | name         | post11                               |
    +--------------+--------------------------------------+


    ironic --ironic-api-version 1.11 node-list

    +--------------------------------------+--------+---------------+-------------+--------------------+-------------+
    | UUID                                 | Name   | Instance UUID | Power State | Provisioning State | Maintenance |
    +--------------------------------------+--------+---------------+-------------+--------------------+-------------+
    | 0eb013bb-1e4b-4f4c-94b5-2e7468242611 | post11 | None          | None        | enroll             | False       |
    +--------------------------------------+--------+---------------+-------------+--------------------+-------------+

In order for nodes to be available for deploying workloads on them, nodes
must be in the ``available`` provision state. To do this, nodes
created with API version 1.11 and above must be moved from the ``enroll`` state
to the ``manageable`` state and then to the ``available`` state.

To move a node to a different provision state, use the
``node-set-provision-state`` command.

.. note:: Since it is an asychronous call, the response for
          ``ironic node-set-provision-state`` will not indicate whether the
          transition succeeded or not. You can check the status of the
          operation via ``ironic node-show``. If it was successful,
          ``provision_state`` will be in the desired state. If it failed,
          there will be information in the node's ``last_error``.

After creating a node and before moving it from its initial provision state of
``enroll``, basic power and port information needs to be configured on the node.
The Bare Metal service needs this information because it verifies that it is
capable of controlling the node when transitioning the node from ``enroll`` to
``manageable`` state.

To move a node from ``enroll`` to ``manageable`` provision state::

    ironic --ironic-api-version 1.11 node-set-provision-state $NODE_UUID manage

    ironic node-show $NODE_UUID

    +------------------------+--------------------------------------------------------------------+
    | Property               | Value                                                              |
    +------------------------+--------------------------------------------------------------------+
    | ...                    | ...                                                                |
    | provision_state        | manageable                                                         | <- verify correct state
    | uuid                   | 0eb013bb-1e4b-4f4c-94b5-2e7468242611                               |
    | ...                    | ...                                                                |
    +------------------------+--------------------------------------------------------------------+

When a node is moved from the ``manageable`` to ``available`` provision
state, the node will go through automated cleaning if configured to do so (see
:ref:`CleaningNetworkSetup`).
To move a node from ``manageable`` to ``available`` provision state::

    ironic --ironic-api-version 1.11 node-set-provision-state $NODE_UUID provide

    ironic node-show $NODE_UUID

    +------------------------+--------------------------------------------------------------------+
    | Property               | Value                                                              |
    +------------------------+--------------------------------------------------------------------+
    | ...                    | ...                                                                |
    | provision_state        | available                                                          | < - verify correct state
    | uuid                   | 0eb013bb-1e4b-4f4c-94b5-2e7468242611                               |
    | ...                    | ...                                                                |
    +------------------------+--------------------------------------------------------------------+


For more details on the Bare Metal service's state machine, see the
`state machine <http://docs.openstack.org/developer/ironic/dev/states.html>`_
documentation.


Logical names
-------------
Beginning with the Kilo release a Node may also be referred to by a
logical name as well as its UUID. Names can be assigned either when
creating the node by adding the ``-n`` option to the ``node-create`` command or
by updating an existing node with the ``node-update`` command.

Node names must be unique, and conform to:

- rfc952_
- rfc1123_
- wiki_hostname_

The node is named 'example' in the following examples:
::

    ironic node-create -d agent_ipmitool -n example

or::

    ironic node-update $NODE_UUID add name=example


Once assigned a logical name, a node can then be referred to by name or
UUID interchangeably.
::

    ironic node-create -d agent_ipmitool -n example

    +--------------+--------------------------------------+
    | Property     | Value                                |
    +--------------+--------------------------------------+
    | uuid         | 71e01002-8662-434d-aafd-f068f69bb85e |
    | driver_info  | {}                                   |
    | extra        | {}                                   |
    | driver       | agent_ipmitool                       |
    | chassis_uuid |                                      |
    | properties   | {}                                   |
    | name         | example                              |
    +--------------+--------------------------------------+


    ironic node-show example

    +------------------------+--------------------------------------+
    | Property               | Value                                |
    +------------------------+--------------------------------------+
    | target_power_state     | None                                 |
    | extra                  | {}                                   |
    | last_error             | None                                 |
    | updated_at             | 2015-04-24T16:23:46+00:00            |
    | ...                    | ...                                  |
    | instance_info          | {}                                   |
    +------------------------+--------------------------------------+

.. _rfc952: http://tools.ietf.org/html/rfc952
.. _rfc1123: http://tools.ietf.org/html/rfc1123
.. _wiki_hostname: http://en.wikipedia.org/wiki/Hostname


.. _inspection:

Hardware Inspection
-------------------

Starting with the Kilo release, Bare Metal service supports hardware inspection
that simplifies enrolling nodes.
Inspection allows Bare Metal service to discover required node properties
once required ``driver_info`` fields (for example, IPMI credentials) are set
by an operator. Inspection will also create the Bare Metal service ports for the
discovered ethernet MACs. Operators will have to manually delete the Bare Metal
service ports for which physical media is not connected. This is required due
to the `bug 1405131 <https://bugs.launchpad.net/ironic/+bug/1405131>`_.

There are two kinds of inspection supported by Bare Metal service:

#. Out-of-band inspection is currently implemented by iLO drivers, listed at
   :ref:`ilo`.

#. In-band inspection is performed by utilizing the ironic-inspector_ project.
   This is supported by the following drivers::

    pxe_drac
    pxe_ipmitool
    pxe_ipminative
    pxe_ssh

  This feature needs to be explicitly enabled in the configuration
  by setting ``enabled = True`` in ``[inspector]`` section.
  You must additionally install python-ironic-inspector-client_ to use
  this functionality.
  You must set ``service_url`` if the ironic-inspector service is
  being run on a separate host from the ironic-conductor service, or is using
  non-standard port.

  In order to ensure that ports in Bare Metal service are synchronized with
  NIC ports on the node, the following settings in the ironic-inspector
  configuration file must be set::

    [processing]
    add_ports = all
    keep_ports = present

  .. note::
    During Kilo cycle we used on older verions of Inspector called
    ironic-discoverd_. Inspector is expected to be a mostly drop-in
    replacement, and the same client library should be used to connect to both.

    For Kilo, install ironic-discoverd_ of version 1.1.0 or higher
    instead of python-ironic-inspector-client and use ``[discoverd]`` option
    group in both Bare Metal service and ironic-discoverd configuration
    files instead of ones provided above.

Inspection can be initiated using node-set-provision-state.
The node should be in MANAGEABLE state before inspection is initiated.

* Move node to manageable state::

    ironic node-set-provision-state <node_UUID> manage

* Initiate inspection::

    ironic node-set-provision-state <node_UUID> inspect

.. note::
    The above commands require the python-ironicclient_ to be version 0.5.0 or greater.

.. _ironic-discoverd: https://pypi.python.org/pypi/ironic-discoverd
.. _python-ironic-inspector-client: https://pypi.python.org/pypi/python-ironic-inspector-client
.. _python-ironicclient: https://pypi.python.org/pypi/python-ironicclient

Specifying the disk for deployment
==================================

Starting with the Kilo release, Bare Metal service supports passing
hints to the deploy ramdisk about which disk it should pick for the
deployment. The list of support hints is:

* model (STRING): device identifier
* vendor (STRING): device vendor
* serial (STRING): disk serial number
* size (INT): size of the device in GiB

  .. note::
    A node's 'local_gb' property is often set to a value 1 GiB less than the
    actual disk size to account for partitioning (this is how DevStack, TripleO
    and Ironic Inspector work, to name a few). However, in this case ``size``
    should be the actual size. For example, for a 128 GiB disk ``local_gb``
    will be 127, but size hint will be 128.

* wwn (STRING): unique storage identifier
* wwn_with_extension (STRING): unique storage identifier with the vendor extension appended
* wwn_vendor_extension (STRING): unique vendor storage identifier
* name (STRING): the device name, e.g /dev/md0


  .. warning::
     The root device hint name should only be used for devices with
     constant names (e.g RAID volumes). For SATA, SCSI and IDE disk
     controllers this hint is not recommended because the order in which
     the device nodes are added in Linux is arbitrary, resulting in
     devices like /dev/sda and /dev/sdb `switching around at boot time
     <https://access.redhat.com/documentation/en-US/Red_Hat_Enterprise_Linux/7/html/Storage_Administration_Guide/persistent_naming.html>`_.


To associate one or more hints with a node, update the node's properties
with a ``root_device`` key, for example::

    ironic node-update <node-uuid> add properties/root_device='{"wwn": "0x4000cca77fc4dba1"}'


That will guarantee that Bare Metal service will pick the disk device that
has the ``wwn`` equal to the specified wwn value, or fail the deployment if it
can not be found.

.. note::
    If multiple hints are specified, a device must satisfy all the hints.


.. _EnableHTTPSinSwift:

Enabling HTTPS in Swift
=======================

The drivers using virtual media use swift for storing boot images
and node configuration information (contains sensitive information for Ironic
conductor to provision bare metal hardware).  By default, HTTPS is not enabled
in swift. HTTPS is required to encrypt all communication between swift and Ironic
conductor and swift and bare metal (via virtual media).  It can be enabled in one
of the following ways:

* `Using an SSL termination proxy
  <http://docs.openstack.org/security-guide/secure-communication/tls-proxies-and-http-services.html>`_

* `Using native SSL support in swift
  <http://docs.openstack.org/developer/swift/deployment_guide.html>`_
  (recommended only for testing purpose by swift).

Using Bare Metal service as a standalone service
================================================

Starting with the Kilo release, it's possible to use Bare Metal service without
other OpenStack services.

You should make the following changes to ``/etc/ironic/ironic.conf``:

#. To disable usage of Identity service tokens::

    [DEFAULT]
    ...
    auth_strategy=none

#. If you want to disable the Networking service, you should have your network
   pre-configured to serve DHCP and TFTP for machines that you're deploying.
   To disable it, change the following lines::

    [dhcp]
    ...
    dhcp_provider=none

   .. note::
      If you disabled the Networking service and the driver that you use is
      supported by at most one conductor, PXE boot will still work for your
      nodes without any manual config editing. This is because you know all
      the DHCP options that will be used for deployment and can set up your
      DHCP server appropriately.

      If you have multiple conductors per driver, it would be better to use
      Networking since it will do all the dynamically changing configurations
      for you.

If you don't use Image service, it's possible to provide images to Bare Metal
service via hrefs.

.. note::
   At the moment, only two types of hrefs are acceptable instead of Image
   service UUIDs: HTTP(S) hrefs (for example, "http://my.server.net/images/img")
   and file hrefs (file:///images/img).

There are however some limitations for different drivers:

* If you're using one of the drivers that use agent deploy method (namely,
  ``agent_ilo``, ``agent_ipmitool``, ``agent_pyghmi``, ``agent_ssh`` or
  ``agent_vbox``) you have to know MD5 checksum for your instance image. To
  compute it, you can use the following command::

   md5sum image.qcow2
   ed82def8730f394fb85aef8a208635f6  image.qcow2

  Apart from that, because of the way the agent deploy method works, image
  hrefs can use only HTTP(S) protocol.

* If you're using ``iscsi_ilo`` or ``agent_ilo`` driver, Object Storage service
  is required, as these drivers need to store floppy image that is used to pass
  parameters to deployment iso. For this method also only HTTP(S) hrefs are
  acceptable, as HP iLO servers cannot attach other types of hrefs as virtual
  media.

* Other drivers use PXE deploy method and there are no special requirements
  in this case.

Steps to start a deployment are pretty similar to those when using Compute:

#. To use the `ironic CLI <http://docs.openstack.org/developer/python-ironicclient/cli.html>`_,
   set up these environment variables. Since no authentication strategy is
   being used, the value can be any string for OS_AUTH_TOKEN. IRONIC_URL is
   the URL of the ironic-api process.
   For example::

    export OS_AUTH_TOKEN=fake-token
    export IRONIC_URL=http://localhost:6385/

#. Create a node in Bare Metal service. At minimum, you must specify the driver
   name (for example, "pxe_ipmitool"). You can also specify all the required
   driver parameters in one command. This will return the node UUID::

    ironic node-create -d pxe_ipmitool -i ipmi_address=ipmi.server.net \
    -i ipmi_username=user -i ipmi_password=pass \
    -i deploy_kernel=file:///images/deploy.vmlinuz \
    -i deploy_ramdisk=http://my.server.net/images/deploy.ramdisk

    +--------------+--------------------------------------------------------------------------+
    | Property     | Value                                                                    |
    +--------------+--------------------------------------------------------------------------+
    | uuid         | be94df40-b80a-4f63-b92b-e9368ee8d14c                                     |
    | driver_info  | {u'deploy_ramdisk': u'http://my.server.net/images/deploy.ramdisk',       |
    |              | u'deploy_kernel': u'file:///images/deploy.vmlinuz', u'ipmi_address':     |
    |              | u'ipmi.server.net', u'ipmi_username': u'user', u'ipmi_password':         |
    |              | u'******'}                                                               |
    | extra        | {}                                                                       |
    | driver       | pxe_ipmitool                                                             |
    | chassis_uuid |                                                                          |
    | properties   | {}                                                                       |
    +--------------+--------------------------------------------------------------------------+

   Note that here deploy_kernel and deploy_ramdisk contain links to
   images instead of Image service UUIDs.

#. As in case of Compute service, you can also provide ``capabilities`` to node
   properties, but they will be used only by Bare Metal service (for example,
   boot mode). Although you don't need to add properties like ``memory_mb``,
   ``cpus`` etc. as Bare Metal service will require UUID of a node you're
   going to deploy.

#. Then create a port to inform Bare Metal service of the network interface
   cards which are part of the node by creating a port with each NIC's MAC
   address. In this case, they're used for naming of PXE configs for a node::

    ironic port-create -n $NODE_UUID -a $MAC_ADDRESS

#. As there is no Compute service flavor and instance image is not provided with
   nova boot command, you also need to specify some fields in ``instance_info``.
   For PXE deployment, they are ``image_source``, ``kernel``, ``ramdisk``,
   ``root_gb``::

    ironic node-update $NODE_UUID add instance_info/image_source=$IMG \
    instance_info/kernel=$KERNEL instance_info/ramdisk=$RAMDISK \
    instance_info/root_gb=10

   Here $IMG, $KERNEL, $RAMDISK can also be HTTP(S) or file hrefs. For agent
   drivers, you don't need to specify kernel and ramdisk, but MD5 checksum of
   instance image is required::

    ironic node-update $NODE_UUID add instance_info/image_checksum=$MD5HASH

#. Validate that all parameters are correct::

    ironic node-validate $NODE_UUID

    +------------+--------+----------------------------------------------------------------+
    | Interface  | Result | Reason                                                         |
    +------------+--------+----------------------------------------------------------------+
    | console    | False  | Missing 'ipmi_terminal_port' parameter in node's driver_info.  |
    | deploy     | True   |                                                                |
    | management | True   |                                                                |
    | power      | True   |                                                                |
    +------------+--------+----------------------------------------------------------------+

#. Now you can start the deployment, run::

    ironic node-set-provision-state $NODE_UUID active

   You can manage provisioning by issuing this command. Valid provision states
   are ``active``, ``rebuild`` and ``deleted``.

For iLO drivers, fields that should be provided are:

* ``ilo_deploy_iso`` under ``driver_info``;

* ``ilo_boot_iso``, ``image_source``, ``root_gb`` under ``instance_info``.

.. note::
   Before Liberty release Ironic was not able to track non-Glance images'
   content changes. Starting with Liberty, it is possible to do so using image
   modification date. For example, for HTTP image, if 'Last-Modified' header
   value from response to a HEAD request to
   "http://my.server.net/images/deploy.ramdisk" is greater than cached image
   modification time, Ironic will re-download the content. For "file://"
   images, the file system modification time is used.


Other references
----------------

* `Enabling local boot without Compute`_


Enabling the configuration drive (configdrive)
==============================================

Starting with the Kilo release, the Bare Metal service supports exposing
a configuration drive image to the instances.

The configuration drive is usually used in conjunction with the Compute
service, but the Bare Metal service also offers a standalone way of using it.
The following sections will describe both methods.


When used with Compute service
------------------------------

To enable the configuration drive when deploying an instance, pass
``--config-drive true`` parameter to the ``nova boot`` command, for example::

    nova boot --config-drive true --flavor baremetal --image test-image instance-1

It's also possible to enable the configuration drive automatically on
all instances by configuring the ``OpenStack Compute service`` to always
create a configuration drive by setting the following option in the
``/etc/nova/nova.conf`` file, for example::

    [DEFAULT]
    ...

    force_config_drive=True


When used standalone
--------------------

When used without the Compute service, the operator needs to create a configuration drive
and provide the file or HTTP URL to the Bare Metal service.

For the format of the configuration drive, Bare Metal service expects a
``gzipped`` and ``base64`` encoded ISO 9660 [*]_ file with a ``config-2``
label. The
`ironic client <https://github.com/openstack/python-ironicclient>`_
can generate a configuration drive in the `expected format`_. Just pass a
directory path containing the files that will be injected into it via the
``--config-drive`` parameter of the ``node-set-provision-state`` command,
for example::

    ironic node-set-provision-state --config-drive /dir/configdrive_files $node_identifier active


Accessing the configuration drive data
--------------------------------------

When the configuration drive is enabled, the Bare Metal service will create a partition on the
instance disk and write the configuration drive image onto it. The
configuration drive must be mounted before use. This is performed
automatically by many tools, such as cloud-init and cloudbase-init. To mount
it manually on a Linux distribution that supports accessing devices by labels,
simply run the following::

    mkdir -p /mnt/config
    mount /dev/disk/by-label/config-2 /mnt/config


If the guest OS doesn't support accessing devices by labels, you can use
other tools such as ``blkid`` to identify which device corresponds to
the configuration drive and mount it, for example::

    CONFIG_DEV=$(blkid -t LABEL="config-2" -odevice)
    mkdir -p /mnt/config
    mount $CONFIG_DEV /mnt/config


.. [*] A config drive could also be a data block with a VFAT filesystem
       on it instead of ISO 9660. But it's unlikely that it would be needed
       since ISO 9660 is widely supported across operating systems.


Cloud-init integration
----------------------

The configuration drive can be
especially useful when used with `cloud-init
<http://cloudinit.readthedocs.org/en/latest/topics/datasources.html#config-drive>`_,
but in order to use it we should follow some rules:

* ``Cloud-init`` data should be organized in the `expected format`_.


* Since the Bare Metal service uses a disk partition as the configuration drive,
  it will only work with
  `cloud-init version >= 0.7.5 <http://bazaar.launchpad.net/~cloud-init-dev/cloud-init/trunk/view/head:/ChangeLog>`_.


* ``Cloud-init`` has a collection of data source modules, so when
  building the image with `disk-image-builder`_ we have to define
  ``DIB_CLOUD_INIT_DATASOURCES`` environment variable and set the
  appropriate sources to enable the configuration drive, for example::

    DIB_CLOUD_INIT_DATASOURCES="ConfigDrive, OpenStack" disk-image-create -o fedora-cloud-image fedora baremetal

  For more information see `how to configure cloud-init data sources
  <http://docs.openstack.org/developer/diskimage-builder/elements/cloud-init-datasources/README.html>`_.

.. _`expected format`: http://docs.openstack.org/user-guide/cli_config_drive.html#openstack-metadata-format

.. _BuildingDeployRamdisk:

Building or downloading a deploy ramdisk image
==============================================

Ironic depends on having an image with the ironic-python-agent_ (IPA)
service running on it for controlling and deploying bare metal nodes.

You can download a pre-built version of the deploy ramdisk built with
the `CoreOS tools`_ at:

* `CoreOS deploy kernel <http://tarballs.openstack.org/ironic-python-agent/coreos/files/coreos_production_pxe.vmlinuz>`_
* `CoreOS deploy ramdisk <http://tarballs.openstack.org/ironic-python-agent/coreos/files/coreos_production_pxe_image-oem.cpio.gz>`_

Building from source
--------------------

There are two known methods for creating the deployment image with the
IPA service:

.. _BuildingCoreOSDeployRamdisk:

CoreOS tools
~~~~~~~~~~~~

#. Clone the ironic-python-agent_ project::

    git clone https://github.com/openstack/ironic-python-agent

#. Install the requirements::

    Fedora 21/RHEL7/CentOS7:
        sudo yum install docker gzip util-linux cpio findutils grep gpg

    Fedora 22 or higher:
        sudo dnf install docker gzip util-linux cpio findutils grep gpg

    Ubuntu 14.04 (trusty) or higher:
        sudo apt-get install docker.io gzip uuid-runtime cpio findutils grep gnupg

#. Change directory to ``imagebuild/coreos``::

    cd ironic-python-agent/imagebuild/coreos

#. Start the docker daemon::

    Fedora/RHEL7/CentOS7:
        sudo systemctl start docker

    Ubuntu:
        sudo service docker start

#. Create the image::

    sudo make

#. Or, create an ISO image to boot with virtual media::

    sudo make iso


.. note::
   Once built the deploy ramdisk and kernel will appear inside of a
   directory called ``UPLOAD``.


.. _BuildingDibBasedDeployRamdisk:

disk-image-builder
~~~~~~~~~~~~~~~~~~

#. Install disk-image-builder_ from pip or from your distro's packages::

    sudo pip install diskimage-builder

#. Create the image::

    disk-image-create ironic-agent fedora -o ironic-deploy

   The above command creates the deploy ramdisk and kernel named
   ``ironic-deploy.vmlinuz`` and ``ironic-deploy.initramfs`` in your
   current directory.

#. Or, create an ISO image to boot with virtual media::

    disk-image-create ironic-agent fedora iso -o ironic-deploy

   The above command creates the deploy ISO named ``ironic-deploy.iso``
   in your current directory.

.. note::
   Fedora was used as an example for the base operational system. Please
   check the `diskimage-builder documentation`_ for other supported
   operational systems.

.. _`diskimage-builder documentation`: http://docs.openstack.org/developer/diskimage-builder


Trusted boot with partition image
=================================
Starting with the Liberty release, Ironic supports trusted boot with partition
image. This means at the end of the deployment process, when the node is
rebooted with the new user image, ``trusted boot`` will be performed. It will
measure the node's BIOS, boot loader, Option ROM and the Kernel/Ramdisk, to
determine whether a bare metal node deployed by Ironic should be trusted.

It's important to note that in order for this to work the node being deployed
**must** have Intel `TXT`_ hardware support. The image being deployed with
Ironic must have ``oat-client`` installed within it.

The following will describe how to enable ``trusted boot`` and boot
with PXE and Nova:

#. Create a customized user image with ``oat-client`` installed::

    disk-image-create -u fedora baremetal oat-client -o $TRUST_IMG

   For more information on creating customized images, see `ImageRequirement`_.

#. Enable VT-x, VT-d, TXT and TPM on the node. This can be done manually through
   the BIOS. Depending on the platform, several reboots may be needed.

#. Enroll the node and update the node capability value::

    ironic node-create -d pxe_ipmitool

    ironic node-update $NODE_UUID add properties/capabilities={'trusted_boot':true}

#. Create a special flavor::

    nova flavor-key $TRUST_FLAVOR_UUID set 'capabilities:trusted_boot'=true

#. Prepare `tboot`_ and mboot.c32 and put them into tftp_root or http_root
   directory on all nodes with the ironic-conductor processes::

    Ubuntu:
        cp /usr/lib/syslinux/mboot.c32 /tftpboot/

    Fedora:
        cp /usr/share/syslinux/mboot.c32 /tftpboot/

   *Note: The actual location of mboot.c32 varies among different distribution versions.*

   tboot can be downloaded from
   https://sourceforge.net/projects/tboot/files/latest/download

#. Install an OAT Server. An `OAT Server`_ should be running and configured correctly.

#. Boot an instance with Nova::

    nova boot --flavor $TRUST_FLAVOR_UUID --image $TRUST_IMG --user-data $TRUST_SCRIPT trusted_instance

   *Note* that the node will be measured during ``trusted boot`` and the hash values saved
   into `TPM`_. An example of TRUST_SCRIPT can be found in `trust script example`_.

#. Verify the result via OAT Server.

   This is outside the scope of Ironic. At the moment, users can manually verify the result
   by following the `manual verify steps`_.

.. _`TXT`: http://en.wikipedia.org/wiki/Trusted_Execution_Technology
.. _`tboot`: https://sourceforge.net/projects/tboot
.. _`TPM`: http://en.wikipedia.org/wiki/Trusted_Platform_Module
.. _`OAT Server`: https://github.com/OpenAttestation/OpenAttestation/wiki
.. _`trust script example`: https://wiki.openstack.org/wiki/Bare-metal-trust#Trust_Script_Example
.. _`manual verify steps`: https://wiki.openstack.org/wiki/Bare-metal-trust#Manual_verify_result



Troubleshooting
===============

Once all the services are running and configured properly, and a node has been
enrolled with the Bare Metal service and is in the ``available`` provision
state, the Compute service should detect the node
as an available resource and expose it to the scheduler.

.. note::
   There is a delay, and it may take up to a minute (one periodic task cycle)
   for the Compute service to recognize any changes in the Bare Metal service's
   resources (both additions and deletions).

In addition to watching ``nova-compute`` log files, you can see the available
resources by looking at the list of Compute hypervisors. The resources reported
therein should match the bare metal node properties, and the Compute service flavor.

Here is an example set of commands to compare the resources in Compute
service and Bare Metal service::

    $ ironic node-list
    +--------------------------------------+---------------+-------------+--------------------+-------------+
    | UUID                                 | Instance UUID | Power State | Provisioning State | Maintenance |
    +--------------------------------------+---------------+-------------+--------------------+-------------+
    | 86a2b1bb-8b29-4964-a817-f90031debddb | None          | power off   | available          | False       |
    +--------------------------------------+---------------+-------------+--------------------+-------------+

    $ ironic node-show 86a2b1bb-8b29-4964-a817-f90031debddb
    +------------------------+----------------------------------------------------------------------+
    | Property               | Value                                                                |
    +------------------------+----------------------------------------------------------------------+
    | instance_uuid          | None                                                                 |
    | properties             | {u'memory_mb': u'1024', u'cpu_arch': u'x86_64', u'local_gb': u'10',  |
    |                        | u'cpus': u'1'}                                                       |
    | maintenance            | False                                                                |
    | driver_info            | { [SNIP] }                                                           |
    | extra                  | {}                                                                   |
    | last_error             | None                                                                 |
    | created_at             | 2014-11-20T23:57:03+00:00                                            |
    | target_provision_state | None                                                                 |
    | driver                 | pxe_ipmitool                                                         |
    | updated_at             | 2014-11-21T00:47:34+00:00                                            |
    | instance_info          | {}                                                                   |
    | chassis_uuid           | 7b49bbc5-2eb7-4269-b6ea-3f1a51448a59                                 |
    | provision_state        | available                                                            |
    | reservation            | None                                                                 |
    | power_state            | power off                                                            |
    | console_enabled        | False                                                                |
    | uuid                   | 86a2b1bb-8b29-4964-a817-f90031debddb                                 |
    +------------------------+----------------------------------------------------------------------+

    $ nova hypervisor-show 1
    +-------------------------+--------------------------------------+
    | Property                | Value                                |
    +-------------------------+--------------------------------------+
    | cpu_info                | baremetal cpu                        |
    | current_workload        | 0                                    |
    | disk_available_least    | -                                    |
    | free_disk_gb            | 10                                   |
    | free_ram_mb             | 1024                                 |
    | host_ip                 | [ SNIP ]                             |
    | hypervisor_hostname     | 86a2b1bb-8b29-4964-a817-f90031debddb |
    | hypervisor_type         | ironic                               |
    | hypervisor_version      | 1                                    |
    | id                      | 1                                    |
    | local_gb                | 10                                   |
    | local_gb_used           | 0                                    |
    | memory_mb               | 1024                                 |
    | memory_mb_used          | 0                                    |
    | running_vms             | 0                                    |
    | service_disabled_reason | -                                    |
    | service_host            | my-test-host                         |
    | service_id              | 6                                    |
    | state                   | up                                   |
    | status                  | enabled                              |
    | vcpus                   | 1                                    |
    | vcpus_used              | 0                                    |
    +-------------------------+--------------------------------------+


Maintenance mode
----------------
Maintenance mode may be used if you need to take a node out of the resource
pool. Putting a node in maintenance mode will prevent Bare Metal service from
executing periodic tasks associated with the node. This will also prevent
Compute service from placing a tenant instance on the node by not exposing
the node to the nova scheduler. Nodes can be placed into maintenance mode
with the following command.
::

    $ ironic node-set-maintenance $NODE_UUID on

As of the Kilo release, a maintenance reason may be included with the optional
``--reason`` command line option. This is a free form text field that will be
displayed in the ``maintenance_reason`` section of the ``node-show`` command.
::

    $ ironic node-set-maintenance $UUID on --reason "Need to add ram."

    $ ironic node-show $UUID

    +------------------------+--------------------------------------+
    | Property               | Value                                |
    +------------------------+--------------------------------------+
    | target_power_state     | None                                 |
    | extra                  | {}                                   |
    | last_error             | None                                 |
    | updated_at             | 2015-04-27T15:43:58+00:00            |
    | maintenance_reason     | Need to add ram.                     |
    | ...                    | ...                                  |
    | maintenance            | True                                 |
    | ...                    | ...                                  |
    +------------------------+--------------------------------------+

To remove maintenance mode and clear any ``maintenance_reason`` use the
following command.
::

    $ ironic node-set-maintenance $NODE_UUID off


.. _diskimage-builder: https://github.com/openstack/diskimage-builder
.. _ironic-python-agent: https://github.com/openstack/ironic-python-agent
