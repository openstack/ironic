.. _install-guide:

=====================================
Bare Metal Service Installation Guide
=====================================

Service Overview
================

The Bare Metal Service is a collection of components that provides support to
manage and provision physical machines.

Also known as the ``ironic`` project, the Bare Metal Service interacts with
several other OpenStack services such as:

- the Identity Service (keystone) for request authentication and to
  locate other OpenStack services
- the Image Service (glance) from which to retrieve images
- the Networking Service (neutron) for DHCP and network configuration
- the Compute Service (nova), which leverages the Bare Metal Service to
  manage compute instances on bare metal.

The Bare Metal Service includes the following components:

- ironic-api. A RESTful API that processes application requests by sending
  them to the ironic-conductor over RPC.
- ironic-conductor. Adds/edits/deletes nodes; powers on/off nodes with
  ipmi or ssh; provisions/deploys/decommissions bare metal nodes.
- Ironic client. A command-line interface (CLI) for interacting with
  the Bare Metal Service.

Additionally, the Bare Metal Servive has certain external dependencies, which are
very similar to other OpenStack Services:

- A database to store hardware information and state. You can set the database
  backend type and location. A simple approach is to use the same database
  backend as the Compute Service. Another approach is to use a separate
  database backend to further isolate bare metal resources (and associated
  metadata) from users.
- A queue. A central hub for passing messages. It should use the same
  implementation as that of the Compute Service (typically RabbitMQ).

Install and Configure Prerequisites
===================================

The Bare Metal Service is a collection of components that provides support to
manage and provision physical machines. You can configure these components to
run on separate nodes or the same node. In this guide, the components run on
one node, typically the Compute Service's compute node.

This section shows you how to install and configure the components.

It assumes that the Identity Service, Image Service, Compute Service, and
Networking Service have already been set up.

Configure Identity Service for Bare Metal
-----------------------------------------

#. Create the Bare Metal service user (eg ``ironic``). The service uses this to
   authenticate with the Identity Service. Use the ``service`` tenant and
   give the user the ``admin`` role::

    keystone user-create --name=ironic --pass=IRONIC_PASSWORD --email=ironic@example.com
    keystone user-role-add --user=ironic --tenant=service --role=admin

#. You must register the Bare Metal Service with the Identity Service so that
   other OpenStack services can locate it. To register the service::

    keystone service-create --name=ironic --type=baremetal \
    --description="Ironic bare metal provisioning service"

#. Use the ``id`` property that is returned from the Identity Service when registering
   the service (above), to create the endpoint, and replace IRONIC_NODE
   with your Bare Metal Service's API node::

    keystone endpoint-create \
    --service-id=the_service_id_above \
    --publicurl=http://IRONIC_NODE:6385 \
    --internalurl=http://IRONIC_NODE:6385 \
    --adminurl=http://IRONIC_NODE:6385

Set up the Database for Bare Metal
----------------------------------

The Bare Metal Service stores information in a database. This guide uses the
MySQL database that is used by other OpenStack services.

#. In MySQL, create an ``ironic`` database that is accessible by the
   ``ironic`` user. Replace IRONIC_DBPASSWORD
   with the actual password::

    # mysql -u root -p
    mysql> CREATE DATABASE ironic CHARACTER SET utf8;
    mysql> GRANT ALL PRIVILEGES ON ironic.* TO 'ironic'@'localhost' \
    IDENTIFIED BY 'IRONIC_DBPASSWORD';
    mysql> GRANT ALL PRIVILEGES ON ironic.* TO 'ironic'@'%' \
    IDENTIFIED BY 'IRONIC_DBPASSWORD';

Install the Bare Metal Service
------------------------------

#. Install from packages::

    # Available in Ubuntu 14.04 (trusty)
    apt-get install ironic-api ironic-conductor python-ironicclient

Configure the Bare Metal Service
================================

The Bare Metal Service is configured via its configuration file. This file
is typically located at ``/etc/ironic/ironic.conf``.

Although some configuration options are mentioned here, it is recommended that
you review all the available options so that the Bare Metal Service is
configured for your needs.

#. The Bare Metal Service stores information in a database. This guide uses the
   MySQL database that is used by other OpenStack services.

   Configure the location of the database via the ``connection`` option. In the
   following, replace IRONIC_DBPASSWORD with the password of your ``ironic``
   user, and replace DB_IP with the IP address where the DB server is located::

    [database]
    ...

    # The SQLAlchemy connection string used to connect to the
    # database (string value)
    #connection=<None>
    connection = mysql://ironic:IRONIC_DBPASSWORD@DB_IP/ironic?charset=utf8

#. Configure the Bare Metal Service to use the RabbitMQ message broker by
   setting one or more of these options. Replace RABBIT_HOST with the
   address of the RabbitMQ server.::

    [DEFAULT]
    ...
    # The RabbitMQ broker address where a single node is used
    # (string value)
    rabbit_host=RABBIT_HOST

    # The RabbitMQ userid (string value)
    #rabbit_userid=guest

    # The RabbitMQ password (string value)
    #rabbit_password=guest

    # The RabbitMQ virtual host (string value)
    #rabbit_virtual_host=/

#. Configure the Bare Metal Service to use these credentials with the Identity
   Service. Replace IDENTITY_IP with the IP of the Identity server, and
   replace IRONIC_PASSWORD with the password you chose for the ``ironic``
   user in the Identity Service::

    [DEFAULT]
    ...
    # Method to use for authentication: noauth or keystone.
    # (string value)
    auth_strategy=keystone

    ...
    [keystone_authtoken]

    # Host providing the admin Identity API endpoint (string
    # value)
    #auth_host=127.0.0.1
    auth_host=IDENTITY_IP

    # Port of the admin Identity API endpoint (integer value)
    #auth_port=35357

    # Protocol of the admin Identity API endpoint(http or https)
    # (string value)
    #auth_protocol=https

    # Complete public Identity API endpoint (string value)
    #auth_uri=<None>
    auth_uri=http://IDENTITY_IP:5000/

    # Keystone account username (string value)
    #admin_user=<None>
    admin_user=ironic

    # Keystone account password (string value)
    #admin_password=<None>
    admin_password=IRONIC_PASSWORD

    # Keystone service account tenant name to validate user tokens
    # (string value)
    #admin_tenant_name=admin
    admin_tenant_name=service

    # Directory used to cache files related to PKI tokens (string
    # value)
    #signing_dir=<None>

#. Set the URL (replace NEUTRON_IP) for connecting to the Networking service, to be the
   Networking service endpoint::

    [neutron]

    # URL for connecting to neutron. (string value)
    #url=http://127.0.0.1:9696
    url=http://NEUTRON_IP:9696

#. Configure the Bare Metal Service so that it can communicate with the
   Image Service. Replace GLANCE_IP with the hostname or IP address of
   the Image Service::

    [glance]

    # A list of URL schemes that can be downloaded directly via
    # the direct_url.  Currently supported schemes: [file]. (list
    # value)
    #allowed_direct_url_schemes=

    # Default glance hostname or IP address. (string value)
    #glance_host=$my_ip
    glance_host=GLANCE_IP

    # Default glance port. (integer value)
    #glance_port=9292

    # Default protocol to use when connecting to glance. Set to
    # https for SSL. (string value)
    #glance_protocol=http

    # A list of the glance api servers available to nova. Prefix
    # with https:// for SSL-based glance API servers. Format is
    # [hostname|IP]:port. (string value)
    #glance_api_servers=<None>


#. Create the Bare Metal Service database tables::

    ironic-dbsync --config-file /etc/ironic/ironic.conf

#. Restart the Bare Metal Service::

    service ironic-api restart
    service ironic-conductor restart


Configure Compute Service to use the Bare Metal Service
=======================================================

The Compute Service needs to be configured to use the Bare Metal Service's
driver.  The configuration file for the Compute Service is typically located at
``/etc/nova/nova.conf``. *This configuration file must be modified on the
Compute Service's controller nodes and compute nodes.*

1. Change these configuration options in the ``default`` section, as follows::

    [default]

    # Driver to use for controlling virtualization. Options
    # include: libvirt.LibvirtDriver, xenapi.XenAPIDriver,
    # fake.FakeDriver, baremetal.BareMetalDriver,
    # vmwareapi.VMwareESXDriver, vmwareapi.VMwareVCDriver (string
    # value)
    #compute_driver=<None>
    compute_driver=ironic.nova.virt.ironic.IronicDriver

    # Firewall driver (defaults to hypervisor specific iptables
    # driver) (string value)
    #firewall_driver=<None>
    firewall_driver=nova.virt.firewall.NoopFirewallDriver

    # The scheduler host manager class to use (string value)
    #scheduler_host_manager=nova.scheduler.host_manager.HostManager
    scheduler_host_manager=ironic.nova.scheduler.ironic_host_manager.IronicHostManager

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

3. On the Compute Service's controller nodes, restart ``nova-scheduler`` process::

    service nova-scheduler restart

4. On the Compute Service's compute nodes, restart the ``nova-compute`` process::

    service nova-compute restart


PXE Setup
---------

On the Bare Metal Service node(s) where ``ironic-conductor`` is running,
PXE needs to be set up.

#. Make sure these directories exist::

    sudo mkdir -p /tftproot
    sudo chown -R ironic:LIBVIRT_GROUP -p /tftproot
    mkdir -p /tftproot/pxelinux.cfg

#. Copy the PXE binary to ``/tftproot``. The PXE binary might be found at::

     ubuntu: /usr/lib/syslinux/pxelinux.0
     fedora/RHEL: /usr/share/syslinux/pxelinux.0

