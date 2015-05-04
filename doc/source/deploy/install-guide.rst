.. _install-guide:

=====================================
Bare Metal Service Installation Guide
=====================================

This document pertains to the Kilo (2015.1) release of OpenStack Ironic.  Users
of earlier releases may encounter differences, and are encouraged to look at
earlier versions of this document for guidance.


Service Overview
================

The Bare Metal Service is a collection of components that provides support to
manage and provision physical machines.

Also known as the ``Ironic`` project, the Bare Metal Service may, depending
upon configuration, interact with several other OpenStack services. This
includes:

- the Telemetry (Ceilometer) for consuming the IPMI metrics
- the Identity Service (Keystone) for request authentication and to
  locate other OpenStack services
- the Image Service (Glance) from which to retrieve images and image meta-data
- the Networking Service (Neutron) for DHCP and network configuration
- the Compute Service (Nova) works with Ironic and acts as a user-facing API
  for instance management, while Ironic provides the admin/operator API for
  hardware management. Nova also provides scheduling facilities (matching
  flavors <-> images <-> hardware), tenant quotas, IP assignment, and other
  services which Ironic does not, in and of itself, provide.

- the Block Storage (Cinder) will provide volumes, but the aspect is not yet available.

The Bare Metal Service includes the following components:

- ironic-api: A RESTful API that processes application requests by sending
  them to the ironic-conductor over RPC.
- ironic-conductor: Adds/edits/deletes nodes; powers on/off nodes with
  ipmi or ssh; provisions/deploys/decommissions bare metal nodes.
- ironic-python-agent: A python service which is run in a temporary ramdisk to
  provide ironic-conductor service(s) with remote access and in-band hardware
  control.
- python-ironicclient: A command-line interface (CLI) for interacting with
  the Bare Metal Service.

Additionally, the Bare Metal Service has certain external dependencies, which are
very similar to other OpenStack Services:

- A database to store hardware information and state. You can set the database
  backend type and location. A simple approach is to use the same database
  backend as the Compute Service. Another approach is to use a separate
  database backend to further isolate bare metal resources (and associated
  metadata) from users.
- A queue. A central hub for passing messages. It should use the same
  implementation as that of the Compute Service (typically RabbitMQ).

Optionally, one may wish to utilize the following associated projects for
additional functionality:

- ironic-discoverd_; An associated service which performs in-band hardware
  introspection by PXE booting unregistered hardware into a "discovery ramdisk".
- diskimage-builder_; May be used to customize machine images, create and
  discovery deploy ramdisks, if necessary.

.. _ironic-discoverd: https://github.com/stackforge/ironic-discoverd
.. _diskimage-builder: https://github.com/openstack/diskimage-builder


.. todo: include coreos-image-builder reference here, once the split is done


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

.. error::
    If the keystone endpoint-create operation returns an error about not being
    able to find the region "regionOne", the error is due to this keystone bug:
    https://bugs.launchpad.net/keystone/+bug/1400589. As a workaround until
    that bug is fixed you can force the creation of "RegionOne" by passing
    --region=RegionOne as an argument to the keystone endpoint-create command.

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

    ironic-dbsync --config-file /etc/ironic/ironic.conf create_schema

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
    compute_driver=nova.virt.ironic.IronicDriver

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

.. _NeutronFlatNetworking:

Configure Neutron to communicate with the Bare Metal Server
===========================================================

Neutron needs to be configured so that the bare metal server can communicate
with the OpenStack Networking service for DHCP, PXE Boot and other
requirements. This section describes how to configure Neutron for a single flat
network use case for bare metal provisioning.

You will also need to provide Ironic with the MAC address(es) of each Node that
it is provisioning; Ironic in turn will pass this information to Neutron for
DHCP and PXE Boot configuration. An example of this is shown in the
`Enrollment`_ section.

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
   OpenStack (and Bare Metal services) and the bare metal nodes using eth2.
   Replace eth2 with the interface on the neutron node which you are
   using to connect to the Bare Metal Service::

    ovs-vsctl add-br br-eth2
    ovs-vsctl add-port br-eth2 eth2

#. Restart the Open vSwitch agent::

    service neutron-plugin-openvswitch-agent restart

#. On restarting the Neutron Open vSwitch agent, the veth pair between
   the bridges br-int and br-eth2 is automatically created.

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

Configure the Bare Metal Service for Cleaning
=============================================

#. If you configure Ironic to use :ref:`cleaning` (which is enabled by
   default), you will need to set the ``cleaning_network_uuid`` configuration
   option. Note the network UUID (the `id` field) of the network you created in
   :ref:`NeutronFlatNetworking` or another network you created for cleaning::

    neutron net-list

#. Configure the cleaning network UUID via the ``cleaning_network_uuid``
   option in the Ironic configuration file (/etc/ironic/ironic.conf). In the
   following, replace NETWORK_UUID with the UUID you noted in the previous
   step::

    [neutron]
    ...

    # UUID of the network to create Neutron ports on when booting
    # to a ramdisk for cleaning/zapping using Neutron DHCP (string
    # value)
    #cleaning_network_uuid=<None>
    cleaning_network_uuid = NETWORK_UUID

#. Restart the Bare Metal Service's ironic-conductor::

    service ironic-conductor restart

Image Requirements
==================

Bare Metal provisioning requires two sets of images: the deploy images
and the user images. The deploy images are used by the Bare Metal Service
to prepare the bare metal server for actual OS deployment. Whereas the
user images are installed on the bare metal server to be used by the
end user. Below are the steps to create the required images and add
them to Glance service:

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

       disk-image-create ubuntu baremetal dhcp-all-interfaces -o my-image

     The above command creates *my-image.qcow2*, *my-image.vmlinuz* and
     *my-image.initrd* files. If you want to use Fedora image, replace
     *ubuntu* with *fedora* in the above command. *my-image.qcow2* is
     used while deploying the actual OS the users will run. The images
     *my-image.vmlinuz* and *my-image.initrd* are used for booting after
     deploying the bare metal with my-image.qcow2.

   - Build the deploy image::

       ramdisk-image-create ubuntu deploy-ironic \
       -o my-deploy-ramdisk

     The above command creates *my-deploy-ramdisk.kernel* and
     *my-deploy-ramdisk.initramfs* files which are used initially for
     preparing the server (creating disk partitions) before the actual
     OS deploy. If you want to use a Fedora image, replace *ubuntu* with
     *fedora* in the above command.

2. Add the user images to glance

   Load all the images created in the below steps into Glance, and
   note the glance image UUIDs for each one as it is generated.

   - Add the kernel and ramdisk images to glance::

        glance image-create --name my-kernel --is-public True \
        --disk-format aki  < my-image.vmlinuz

     Store the image uuid obtained from the above step as
     *$MY_VMLINUZ_UUID*.

     ::

        glance image-create --name my-image.initrd --is-public True \
        --disk-format ari  < my-image.initrd

     Store the image UUID obtained from the above step as
     *$MY_INITRD_UUID*.

   - Add the *my-image* to glance which is going to be the OS
     that the user is going to run. Also associate the above created
     images with this OS image. These two operations can be done by
     executing the following command::

        glance image-create --name my-image --is-public True \
        --disk-format qcow2 --container-format bare --property \
        kernel_id=$MY_VMLINUZ_UUID --property \
        ramdisk_id=$MY_INITRD_UUID < my-image.qcow2

   - *Note:* To deploy a whole disk image, a kernel_id and a ramdisk_id
     shouldn't be associated with the image. An example is as follows::

         glance image-create --name my-whole-disk-image --is-public True \
         --disk-format qcow2 \
         --container-format bare < my-whole-disk-image.qcow2

3. Add the deploy images to glance

   Add the *my-deploy-ramdisk.kernel* and
   *my-deploy-ramdisk.initramfs* images to glance::

        glance image-create --name deploy-vmlinuz --is-public True \
        --disk-format aki < my-deploy-ramdisk.kernel

   Store the image UUID obtained from the above step as
   *$DEPLOY_VMLINUZ_UUID*.

   ::

        glance image-create --name deploy-initrd --is-public True \
        --disk-format ari < my-deploy-ramdisk.initramfs

   Store the image UUID obtained from the above step as
   *$DEPLOY_INITRD_UUID*.

Flavor Creation
===============

You'll need to create a special Bare Metal flavor in Nova. The flavor is
mapped to the bare metal server through the hardware specifications.

#. Change these to match your hardware::

    RAM_MB=1024
    CPU=2
    DISK_GB=100
    ARCH={i686|x86_64}

#. Create the baremetal flavor by executing the following command::

    nova flavor-create my-baremetal-flavor auto $RAM_MB $DISK_GB $CPU

   *Note: You can replace auto with your own flavor id.*

#. A flavor can include a set of key/value pairs called extra_specs.
   In case of Icehouse version of Ironic, you need to associate the
   deploy ramdisk and deploy kernel images to the flavor as flavor-keys.
   But in case of Juno and higher versions, this is deprecated. Because these
   may vary between nodes in a heterogeneous environment, the deploy kernel
   and ramdisk images should be associated with each node's driver_info.

   - **Icehouse** version of Ironic::

      nova flavor-key my-baremetal-flavor set \
      cpu_arch=$ARCH \
      "baremetal:deploy_kernel_id"=$DEPLOY_VMLINUZ_UUID \
      "baremetal:deploy_ramdisk_id"=$DEPLOY_INITRD_UUID

   - **Juno** and higher versions of Ironic::

      nova flavor-key my-baremetal-flavor set cpu_arch=$ARCH

     Associate the deploy ramdisk and deploy kernel images each of your
     node's driver_info::

      ironic node-update $NODE_UUID add \
      driver_info/pxe_deploy_kernel=$DEPLOY_VMLINUZ_UUID \
      driver_info/pxe_deploy_ramdisk=$DEPLOY_INITRD_UUID \

Setup the drivers for Bare Metal Service
========================================

PXE Setup
---------

If you will be using PXE, it needs to be set up on the Bare Metal Service
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

    Fedora/RHEL:
        sudo yum install tftp-server syslinux-tftpboot

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

    Fedora:
        sudo cp /boot/extlinux/chain.c32 /tftpboot

#. If the version of syslinux is **greater than** 4 we also need to make sure
   that we copy the library modules into the ``/tftpboot`` directory [2]_
   [1]_::

    Ubuntu:
        sudo cp /usr/lib/syslinux/modules/*/ldlinux.* /tftpboot

#. Create a map file in the tftp boot directory (``/tftpboot``)::

    echo 'r ^([^/]) /tftpboot/\1' > /tftpboot/map-file
    echo 'r ^(/tftpboot/) /tftpboot/\2' >> /tftpboot/map-file

#. Enable tftp map file, modify ``/etc/xinetd.d/tftp`` as below and restart xinetd
   service::

    server_args = -v -v -v -v -v --map-file /tftpboot/map-file /tftpboot

.. [1] On **Fedora/RHEL** the ``syslinux-tftpboot`` package already install
       the library modules and PXE image at ``/tftpboot``. If the TFTP server
       is configured to listen to a different directory you should copy the
       contents of ``/tftpboot`` to the configured directory
.. [2] http://www.syslinux.org/wiki/index.php/Library_modules


PXE UEFI Setup
--------------

If you want to deploy on a UEFI supported bare metal, perform these additional
steps on the Ironic conductor node to configure PXE UEFI environment.

#. Download and untar the elilo bootloader version >= 3.16 from
   http://sourceforge.net/projects/elilo/::

    sudo tar zxvf elilo-3.16-all.tar.gz

#. Copy the elilo boot loader image to ``/tftpboot`` directory::

    sudo cp ./elilo-3.16-x86_64.efi /tftpboot/elilo.efi

#. Update the Ironic node with ``boot_mode`` capability in node's properties
   field::

    ironic node-update <node-uuid> add properties/capabilities='boot_mode:uefi'

#. Make sure that bare metal node is configured to boot in UEFI boot mode and
   boot device is set to network/pxe.

   NOTE: ``pxe_ilo`` driver supports automatic setting of UEFI boot mode and
   boot device on the baremetal node. So this step is not required for
   ``pxe_ilo`` driver.

For more information on configuring boot modes, refer boot_mode_support_.


iPXE Setup
----------

An alternative to PXE boot, iPXE was introduced in the Juno release
(2014.2.0) of Ironic.

If you will be using iPXE to boot instead of PXE, iPXE needs to be set up
on the Bare Metal Service node(s) where ``ironic-conductor`` is running.

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

   The Bare Metal Service's configuration file (/etc/ironic/ironic.conf)
   should be edited accordingly to specify the TFTP and HTTP root
   directories and server addresses. For example::

    [pxe]

    # Ironic compute node's http root path. (string value)
    http_root=/httpboot

    # Ironic compute node's tftp root path. (string value)
    tftp_root=/tftpboot

    # IP address of Ironic compute node's tftp server. (string
    # value)
    tftp_server=192.168.0.2

    # Ironic compute node's HTTP server URL. Example:
    # http://192.1.2.3:8080 (string value)
    http_url=http://192.168.0.2:8080

#. Install the iPXE package with the boot images::

    Ubuntu:
        apt-get install ipxe

    Fedora/RHEL:
        yum install ipxe-bootimgs

#. Copy the iPXE boot image (undionly.kpxe) to ``/tftpboot``. The binary
   might be found at::

    Ubuntu:
        cp /usr/lib/ipxe/undionly.kpxe /tftpboot

    Fedora/RHEL:
        cp /usr/share/ipxe/undionly.kpxe /tftpboot

    *Note: If the packaged version of the iPXE boot image doesn't
    work for you or you want to build one from source take a look at
    http://ipxe.org/download for more information on preparing iPXE image.*

#. Enable/Configure iPXE in the Bare Metal Service's configuration file
   (/etc/ironic/ironic.conf)::

    [pxe]

    # Enable iPXE boot. (boolean value)
    ipxe_enabled=True

    # Neutron bootfile DHCP parameter. (string value)
    pxe_bootfile_name=undionly.kpxe

    # Template file for PXE configuration. (string value)
    pxe_config_template=$pybasedir/drivers/modules/ipxe_config.template

#. Restart the ``ironic-conductor`` process::

    service ironic-conductor restart


Neutron configuration
---------------------

DHCP requests from iPXE need to have a DHCP tag called ``ipxe``, in order
for the DHCP server to tell the client to get the boot.ipxe script via
HTTP. Otherwise, if the tag isn't there, the DHCP server will tell the
DHCP client to chainload the iPXE image (undionly.kpxe). Neutron needs to
be configured to create this DHCP tag, since it isn't create by default.

#. Create a custom ``dnsmasq.conf`` file with a setting for the ipxe tag. For
   example, the following creates the file ``/etc/dnsmasq-ironic.conf`` ::

    cat > /etc/dnsmasq-ironic.conf << EOF
    dhcp-match=ipxe,175
    EOF


#. In the Neutron DHCP Agent configuration file (typically located at
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

#. This is not the bare metal server’s main IP. The IPMI controller
   should have it’s own unique IP.

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

Ironic supports sending IPMI sensor data to Ceilometer with pxe_ipmitool,
pxe_ipminative, agent_ipmitool, agent_pyghmi, agent_ilo, iscsi_ilo, pxe_ilo,
and with pxe_irmc driver starting from Kilo release. By default, support for
sending IPMI sensor data to Ceilometer is disabled. If you want to enable it,
you should make the following two changes in ``ironic.conf``:

* ``notification_driver = messaging`` in the ``DEFAULT`` section
* ``send_sensor_data = true`` in the ``conductor`` section

If you want to customize the sensor types which will be sent to Ceilometer,
change the ``send_sensor_data_types`` option. For example, the below settings
will send Temperature,Fan,Voltage these three sensor types data to Ceilometer:

* send_sensor_data_types=Temperature,Fan,Voltage

Else we use default value 'All' for all the sensor types which supported by
Ceilometer, they are:

* Temperature,Fan,Voltage,Current

.. _boot_mode_support:

Boot mode support
-----------------

The following drivers support setting of boot mode (Legacy BIOS or UEFI).

* ``pxe_ipmitool``

The boot modes can be configured in Ironic in the following way:

* When no boot mode setting is provided, these drivers default the boot_mode
  to Legacy BIOS.

* Only one boot mode (either ``uefi`` or ``bios``) can be configured for
  the node.

* If the operator wants a node to boot always in ``uefi`` mode or ``bios``
  mode, then they may use ``capabilities`` parameter within ``properties``
  field of an Ironic node.  The operator must manually set the appropriate
  boot mode on the bare metal node.

  To configure a node in ``uefi`` mode, then set ``capabilities`` as below::

    ironic node-update <node-uuid> add properties/capabilities='boot_mode:uefi'

  Nodes having ``boot_mode`` set to ``uefi`` may be requested by adding an
  ``extra_spec`` to the Nova flavor::

    nova flavor-key ironic-test-3 set capabilities:boot_mode="uefi"
    nova boot --flavor ironic-test-3 --image test-image instance-1

  If ``capabilities`` is used in ``extra_spec`` as above, Nova scheduler
  (``ComputeCapabilitiesFilter``) will match only Ironic nodes which have
  the ``boot_mode`` set appropriately in ``properties/capabilities``. It will
  filter out rest of the nodes.

  The above facility for matching in Nova can be used in heterogeneous
  environments where there is a mix of ``uefi`` and ``bios`` machines, and
  operator wants to provide a choice to the user regarding boot modes. If
  the flavor doesn't contain ``boot_mode`` and ``boot_mode`` is configured for
  Ironic nodes, then Nova scheduler will consider all nodes and user may get
  either ``bios`` or ``uefi`` machine.


Local boot with partition images
================================

Starting with the Kilo release, Ironic supports local boot with partition
images, meaning that after the deployment the node's subsequent reboots
won't happen via PXE or Virtual Media. Instead, it will boot from a
local boot loader installed on the disk.

It's important to note that in order for this to work the image being
deployed with Ironic **must** contain ``grub2`` installed within it.

Enabling the local boot is different when Ironic is used with Nova and
without it. The following sections will describe both methods.

.. note::
   The local boot feature is dependent upon a updated deploy ramdisk built
   with diskimage-builder_ **version >= 0.1.42** or ironic-python-agent_
   in the kilo-era.

.. _diskimage-builder: https://github.com/openstack/diskimage-builder
.. _ironic-python-agent: https://github.com/openstack/ironic-python-agent


Enabling local boot with Nova
-----------------------------

To enable local boot we need to set a capability on the Ironic node, e.g::

    ironic node-update <node-uuid> add properties/capabilities="boot_option:local"


Nodes having ``boot_option`` set to ``local`` may be requested by adding
an ``extra_spec`` to the Nova flavor, e.g::

    nova flavor-key baremetal set capabilities:boot_option="local"


.. note::
    If the node is configured to use ``UEFI``, Ironic will create an ``EFI
    partition`` on the disk and switch the partition table format to
    ``gpt``. The ``EFI partition`` will be used later by the boot loader
    (which is installed from the deploy ramdisk).


Enabling local boot without Nova
--------------------------------

Since adding ``capabilities`` to the node's properties is only used by
the Nova scheduler to perform more advanced scheduling of instances,
we need a way to enable local boot when Nova is not present. To do that
we can simply specify the capability via the ``instance_info`` attribute
of the node, e.g::

    ironic node-update <node-uuid> add instance_info/capabilities='{"boot_option": "local"}'


Enrollment
==========

After all services have been properly configured, you should enroll your
hardware with Ironic, and confirm that the Compute service sees the available
hardware.

.. note::
   When enrolling Nodes with Ironic, note that the Compute service will not
   be immediately notified of the new resources. Nova's resource tracker
   syncs periodically, and so any changes made directly to Ironic's resources
   will become visible in Nova only after the next run of that periodic task.
   More information is in the `Troubleshooting`_ section below.

.. note::
   Any Ironic Node that is visible to Nova may have a workload scheduled to it,
   if both the ``power`` and ``deploy`` interfaces pass the ``validate`` check.
   If you wish to exclude a Node from Nova's scheduler, for instance so that
   you can perform maintenance on it, you can set the Node to "maintenance" mode.
   For more information see the `Maintenance Mode`_ section below.

Some steps are shown separately for illustration purposes, and may be combined
if desired.

#. Create a Node in Ironic. At minimum, you must specify the driver name (eg,
   "pxe_ipmitool"). This will return the node UUID::

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

   Beginning with the Kilo release a Node may also be referred to by a logical
   name as well as its UUID. To utilize this new feature a name must be
   assigned to the Node. This can be done when the Node is created by
   adding the ``-n`` option to the ``node-create`` command or by updating an
   existing Node with the ``node-update`` command. See `Logical Names`_ for
   examples.

#. Update the Node ``driver_info`` so that Ironic can manage the node. Different
   drivers may require different information about the node. You can determine this
   with the ``driver-properties`` command, as follows::

    ironic driver-properties pxe_ipmitool
    +----------------------+-------------------------------------------------------------------------------------------------------------+
    | Property             | Description                                                                                                 |
    +----------------------+-------------------------------------------------------------------------------------------------------------+
    | ipmi_address         | IP address or hostname of the node. Required.                                                               |
    | ipmi_password        | password. Optional.                                                                                         |
    | ipmi_username        | username; default is NULL user. Optional.                                                                   |
    | ...                  | ...                                                                                                         |
    | pxe_deploy_kernel    | UUID (from Glance) of the deployment kernel. Required.                                                      |
    | pxe_deploy_ramdisk   | UUID (from Glance) of the ramdisk that is mounted at boot time. Required.                                   |
    +----------------------+-------------------------------------------------------------------------------------------------------------+

    ironic node-update $NODE_UUID add \
    driver_info/ipmi_username=$USER \
    driver_info/ipmi_password=$PASS \
    driver_info/ipmi_address=$ADDRESS

   Note that you may also specify all ``driver_info`` parameters during
   ``node-create`` by passing the **-i** option multiple times.

#. Update the Node's properties to match the baremetal flavor you created
   earlier::

    ironic node-update $NODE_UUID add \
    properties/cpus=$CPU \
    properties/memory_mb=$RAM_MB \
    properties/local_gb=$DISK_GB \
    properties/cpu_arch=$ARCH

   As above, these can also be specified at node creation by passing the **-p**
   option to ``node-create`` multiple times.

#. If you wish to perform more advanced scheduling of instances based on
   hardware capabilities, you may add metadata to each Node that will be
   exposed to the Nova Scheduler (see: `ComputeCapabilitiesFilter`_).  A full
   explanation of this is outside of the scope of this document. It can be done
   through the special ``capabilities`` member of Node properties::

    ironic node-update $NODE_UUID add \
    properties/capabilities=key1:val1,key2:val2

#. As mentioned in the `Flavor Creation`_ section, if using the Juno or later
   release of Ironic, you should specify a deploy kernel and ramdisk which
   correspond to the Node's driver, eg::

    ironic node-update $NODE_UUID add \
    driver_info/pxe_deploy_kernel=$DEPLOY_VMLINUZ_UUID \
    driver_info/pxe_deploy_ramdisk=$DEPLOY_INITRD_UUID \

#. You must also inform Ironic of the Network Interface Cards which are part of
   the Node by creating a Port with each NIC's MAC address.  These MAC
   addresses are passed to Neutron during instance provisioning and used to
   configure the network appropriately::

    ironic port-create -n $NODE_UUID -a $MAC_ADDRESS

#. To check if Ironic has the minimum information necessary for a Node's driver
   to function, you may ``validate`` it::

    ironic node-validate $NODE_UUID

    +------------+--------+--------+
    | Interface  | Result | Reason |
    +------------+--------+--------+
    | console    | True   |        |
    | deploy     | True   |        |
    | management | True   |        |
    | power      | True   |        |
    +------------+--------+--------+

  If the Node fails validation, each driver will return information as to why it failed::

   ironic node-validate $NODE_UUID

   +------------+--------+-------------------------------------------------------------------------------------------------------------------------------------+
   | Interface  | Result | Reason                                                                                                                              |
   +------------+--------+-------------------------------------------------------------------------------------------------------------------------------------+
   | console    | None   | not supported                                                                                                                       |
   | deploy     | False  | Cannot validate iSCSI deploy. Some parameters were missing in node's instance_info. Missing are: ['root_gb', 'image_source']        |
   | management | False  | Missing the following IPMI credentials in node's driver_info: ['ipmi_address'].                                                     |
   | power      | False  | Missing the following IPMI credentials in node's driver_info: ['ipmi_address'].                                                     |
   +------------+--------+-------------------------------------------------------------------------------------------------------------------------------------+

.. _ComputeCapabilitiesFilter: http://docs.openstack.org/developer/nova/devref/filter_scheduler.html?highlight=computecapabilitiesfilter


Logical Names
-------------
Beginning with the Kilo release a Node may also be referred to by a
logical name as well as its UUID. Names can be assigned either when
creating the Node by adding the ``-n`` option to the ``node-create`` command or
by updating an existing Node with the ``node-update`` command.

Node names must be unique, and conform to:

- rfc952_
- rfc1123_
- wiki_hostname_

The node is named 'example' in the following examples:
::

    ironic node-create -d agent_ipmitool -n example

or::

    ironic node-update $NODE_UUID add name=example


Once assigned a logical name a Node can then be referred to by name or
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


Hardware Inspection
-------------------

Starting with Kilo release Ironic supports hardware inspection that simplifies
enrolling nodes. Inspection allows Ironic to discover required node properties
once required ``driver_info`` fields (e.g. IPMI credentials) are set
by an operator. Inspection will also create the ironic ports for the
discovered ethernet MACs. Operators will have to manually delete the ironic
ports for which physical media is not connected. This is required due to the
`bug 1405131 <https://bugs.launchpad.net/ironic/+bug/1405131>`_.

There are two kinds of inspection supported by Ironic:

#. Out-of-band inspection is currently implemented by iLO drivers, listed at
   :ref:`ilo`.

#. In-band inspection is performed by utilizing the ironic-discoverd_ project.
   This is supported by the following drivers::

    pxe_drac
    pxe_ipmitool
    pxe_ipminative
    pxe_ssh

  As of Kilo release this feature needs to be explicitly enabled in the
  configuration by setting ``enabled = True`` in ``[discoverd]`` section.
  You must additionally install ``ironic-discoverd`` to use this functionality.
  You must set ``service_url`` if the ironic-discoverd service is
  being run on a separate host from the ironic-conductor service, or is using
  non-standard port.

  In order to ensure that ports in Ironic are synchronized with NIC ports on
  the node, the following settings in the ironic-discoverd configuration file
  must be set::

    [discoverd]
    add_ports = all
    keep_ports = present

  Note: It will require ironic-discoverd of version 1.1.0 or higher.

Inspection can be initiated using node-set-provision-state.
The node should be in MANAGEABLE state before inspection is initiated.

* Move node to manageable state::

    ironic node-set-provision-state <node_UUID> manage

* Initiate inspection::

    ironic node-set-provision-state <node_UUID> inspect

.. note::
    The above commands require the python-ironicclient_ to be version 0.5.0 or greater.

.. _ironic-discoverd: https://github.com/stackforge/ironic-discoverd
.. _python-ironicclient: https://pypi.python.org/pypi/python-ironicclient

Specifying the disk for deployment
==================================

Starting with the Kilo release, Ironic supports passing hints to the
deploy ramdisk about which disk it should pick for the deployment. In
Linux when a server has more than one SATA, SCSI or IDE disk controller,
the order in which their corresponding device nodes are added is arbitrary
[`link`_], resulting in devices like ``/dev/sda`` and ``/dev/sdb`` to
switch around between reboots. Therefore, to guarantee that a specific
disk is always chosen for the deployment, Ironic introduced root device
hints.

The list of support hints is:

* model (STRING): device identifier
* vendor (STRING): device vendor
* serial (STRING): disk serial number
* wwn (STRING): unique storage identifier
* size (INT): size of the device in GiB

To associate one or more hints with a node, update the node's properties
with a ``root_device`` key, e.g::

    ironic node-update <node-uuid> add properties/root_device='{"wwn": "0x4000cca77fc4dba1"}'


That will guarantee that Ironic will pick the disk device that has the
``wwn`` equal to the specified wwn value, or fail the deployment if it
can not be found.

.. note::
    If multiple hints are specified, a device must satisfy all the hints.


.. _`link`: https://access.redhat.com/documentation/en-US/Red_Hat_Enterprise_Linux/7/html/Storage_Administration_Guide/persistent_naming.html


Using Ironic as a standalone service
====================================

Starting with Kilo release, it's possible to use Ironic without other
OpenStack services.

You should make the following changes to ``/etc/ironic/ironic.conf``:

#. To disable usage of Keystone tokens::

    [DEFAULT]
    ...
    auth_strategy=none

#. If you want to disable Neutron, you should have your network pre-configured
   to serve DHCP and TFTP for machines that you're deploying. To disable it,
   change the following lines::

    [dhcp]
    ...
    dhcp_provider=none

   .. note::
      If you disabled Neutron and driver that you use is supported by at most
      one conductor, PXE boot will still work for your nodes without any
      manual config editing. This is because you know all the DHCP options
      that will be used for deployment and can set up your DHCP server
      appropriately.

      If you have multiple conductors per driver, it would be better to use
      Neutron since it will do all the dynamically changing configurations for
      you.

If you don't use Glance, it's possible to provide images to Ironic via hrefs.

.. note::
   At the moment, only two types of hrefs are acceptable instead of Glance
   UUIDs: HTTP(S) hrefs (e.g. "http://my.server.net/images/img") and
   file hrefs (file:///images/img).

There are however some limitations for different drivers:

* If you're using one of the drivers that use agent deploy method (namely,
  ``agent_ilo``, ``agent_ipmitool``, ``agent_pyghmi``, ``agent_ssh`` or
  ``agent_vbox``) you have to know MD5 checksum for your instance image. To
  compute it, you can use the following command::

   md5sum image.qcow2
   ed82def8730f394fb85aef8a208635f6  image.qcow2

  Apart from that, because of the way the agent deploy method works, image
  hrefs can use only HTTP(S) protocol.

* If you're using ``iscsi_ilo`` or ``agent_ilo`` driver, Swift service is
  required, as these drivers need to store floppy image that is used to pass
  parameters to deployment iso. For this method also only HTTP(S) hrefs are
  acceptable, as HP iLO servers cannot attach other types of hrefs as virtual
  media.

* Other drivers use PXE deploy method and there are no special requirements
  in this case.

Steps to start a deployment are pretty similar to those when using Nova:

#. Setup the minimum required environment variables first::

   export OS_AUTH_TOKEN=<token>
   export IRONIC_URL=<ironic api url>

   Example :

   export OS_AUTH_TOKEN=fake-token
   export IRONIC_URL=http://localhost:6385/

#. Create a Node in Ironic. At minimum, you must specify the driver name (eg,
   "pxe_ipmitool"). You can also specify all the required driver parameters in
   one command. This will return the node UUID::

    ironic node-create -d pxe_ipmitool -i ipmi_address=ipmi.server.net \
    -i ipmi_username=user -i ipmi_password=pass \
    -i pxe_deploy_kernel=file:///images/deploy.vmlinuz \
    -i pxe_deploy_ramdisk=http://my.server.net/images/deploy.ramdisk

    +--------------+--------------------------------------------------------------------------+
    | Property     | Value                                                                    |
    +--------------+--------------------------------------------------------------------------+
    | uuid         | be94df40-b80a-4f63-b92b-e9368ee8d14c                                     |
    | driver_info  | {u'pxe_deploy_ramdisk': u'http://my.server.net/images/deploy.ramdisk',   |
    |              | u'pxe_deploy_kernel': u'file:///images/deploy.vmlinuz', u'ipmi_address': |
    |              | u'ipmi.server.net', u'ipmi_username': u'user', u'ipmi_password':         |
    |              | u'******'}                                                               |
    | extra        | {}                                                                       |
    | driver       | pxe_ipmitool                                                             |
    | chassis_uuid |                                                                          |
    | properties   | {}                                                                       |
    +--------------+--------------------------------------------------------------------------+

   Note that here pxe_deploy_kernel and pxe_deploy_ramdisk contain links to
   images instead of Glance UUIDs.

#. As in case of Nova, you can also provide ``capabilities`` to node
   properties, but they will be used only by Ironic (e.g. boot mode). Although
   you don't need to add properties like ``memory_mb``, ``cpus`` etc. as Ironic
   will require UUID of a node you're going to deploy.

#. Then create a port to inform Ironic of the Network Interface Cards which
   are part of the Node by creating a Port with each NIC's MAC address. In this
   case, they're used for naming of PXE configs for a node::

    ironic port-create -n $NODE_UUID -a $MAC_ADDRESS

#. As there is no Nova flavor and instance image is not provided with nova
   boot command, you also need to specify some fields in ``instance_info``.
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

#. Now you can start the deployment, just run::

    ironic node-set-provision-state $NODE_UUID active

   You can manage provisioning by issuing this command. Valid provision states
   are ``active``, ``rebuild`` and ``deleted``.

For iLO drivers, fields that should be provided are:

* ``ilo_deploy_iso`` under ``driver_info``;

* ``ilo_boot_iso``, ``image_source``, ``root_gb`` under ``instance_info``.

.. note::
   There is one limitation in this method - Ironic is not tracking changes of
   content under hrefs that are specified. I.e., if the content under
   "http://my.server.net/images/deploy.ramdisk" changes, Ironic does not know
   about that and does not redownload the content.


Other references
----------------

* `Enabling local boot without Nova`_


Enabling the configuration drive (configdrive)
==============================================

Starting with the Kilo release, Ironic supports exposing a configuration
drive image to the instances.

The configuration drive is usually used in conjunction with Nova, but
Ironic also offers a standalone way of using it. The following sections
will describe both methods.


When used with Nova
-------------------

To enable the configuration drive when deploying an instance, pass
``--config-drive true`` parameter to the ``nova boot`` command, e.g::

    nova boot --config-drive true --flavor baremetal --image test-image instance-1

It's also possible to enable the configuration drive automatically on
all instances by configuring the ``Nova Compute service`` to always
create a configuration drive by setting the following option in the
``/etc/nova/nova.conf`` file, e.g::

    [DEFAULT]
    ...

    force_config_drive=always


When used standalone
--------------------

When used without Nova, the operator needs to create a configuration drive
and provide the file or HTTP URL to Ironic.

For the format of the configuration drive, Ironic expects a ``gzipped``
and ``base64`` encoded ISO 9660 [*]_ file with a ``config-2`` label. The
`Ironic client <https://github.com/openstack/python-ironicclient>`_
can generate a configuration drive in the expected format. Just pass a
directory path containing the files that will be injected into it via the
``--config-drive`` parameter of the ``node-set-provision-state`` command,
e.g::

    ironic node-set-provision-state --config-drive /dir/configdrive_files $node_identifier active


Accessing the configuration drive data
--------------------------------------

When the configuration drive is enabled, Ironic will create a partition on the
instance disk and write the configuration drive image onto it. The
configuration drive must be mounted before use. This is performed
automatically by many tools, such as cloud-init and cloudbase-init. To mount
it manually on a Linux distribution that supports accessing devices by labels,
simply run the following::

    mkdir -p /mnt/config
    mount /dev/disk/by-label/config-2 /mnt/config


If the guest OS doesn't support accessing devices by labels, you can use
other tools such as ``blkid`` to identify which device corresponds to
the configuration drive and mount it, e.g::

    CONFIG_DEV=$(blkid -t LABEL="config-2" -odevice)
    mkdir -p /mnt/config
    mount $CONFIG_DEV /mnt/config


.. [*] A config drive could also be a data block with a VFAT filesystem
       on it instead of ISO 9660. But it's unlikely that it would be needed
       since ISO 9660 is widely supported across operating systems.


Cloud-init integration
----------------------

The configuration drive can be especially
useful when used with ``cloud-init`` [`link
<http://cloudinit.readthedocs.org/en/latest/topics/datasources.html#config-drive>`_],
but in order to use it we should follow some rules:

* ``Cloud-init`` expects a specific format to the data. For
  more information about the expected file layout see [`link
  <http://docs.openstack.org/user-guide/content/enable_config_drive.html#config_drive_contents>`_].


* Since Ironic uses a disk partition as the configuration drive,
  it will only work with ``cloud-init`` version **>= 0.7.5** [`link
  <http://bazaar.launchpad.net/~cloud-init-dev/cloud-init/trunk/view/head:/ChangeLog>`_].


* ``Cloud-init`` has a collection of data source modules, so when
  building the image with `disk-image-builder`_ we have to define
  ``DIB_CLOUD_INIT_DATASOURCES`` environment variable and set the
  appropriate sources to enable the configuration drive, e.g::

    DIB_CLOUD_INIT_DATASOURCES="ConfigDrive, OpenStack" disk-image-create -o fedora-cloud-image fedora baremetal

  See [`link
  <http://docs.openstack.org/developer/diskimage-builder/elements/cloud-init-datasources/README.html>`_]
  for more information.


Troubleshooting
===============

Once all the services are running and configured properly, and a Node is
enrolled with Ironic, the Nova Compute service should detect the Node as an
available resource and expose it to the scheduler.

.. note::
   There is a delay, and it may take up to a minute (one periodic task cycle)
   for Nova to recognize any changes in Ironic's resources (both additions and
   deletions).

In addition to watching ``nova-compute`` log files, you can see the available
resources by looking at the list of Nova hypervisors. The resources reported
therein should match the Ironic Node properties, and the Nova Flavor.

Here is an example set of commands to compare the resources in Nova and Ironic::

    $ ironic node-list
    +--------------------------------------+---------------+-------------+--------------------+-------------+
    | UUID                                 | Instance UUID | Power State | Provisioning State | Maintenance |
    +--------------------------------------+---------------+-------------+--------------------+-------------+
    | 86a2b1bb-8b29-4964-a817-f90031debddb | None          | power off   | None               | False       |
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
    | provision_state        | None                                                                 |
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


Maintenance Mode
----------------
Maintenance mode may be used if you need to take a Node out of the resource
pool. Putting a Node in maintenance mode will prevent Ironic from executing periodic
tasks associated with the Node. This will also prevent Nova from placing a tenant
instance on the Node by not exposing the Node to the Nova scheduler. Nodes can
be placed into maintenance mode with the following command.
::

    $ ironic node-set-maintenance $NODE_UUID on

As of the Kilo release a maintenance reason may be included with the optional
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
