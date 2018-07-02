.. _UCS:

==========
UCS driver
==========

Overview
========

The UCS driver is targeted for UCS Manager managed Cisco UCS B/C series
servers. The ``cisco-ucs-managed`` hardware type enables you to take advantage
of UCS Manager by using the python SDK.

The UCS hardware type can use the Ironic Inspector service for in-band
inspection of equipment. For more information see the `Ironic Inspector
documentation <https://docs.openstack.org/ironic-inspector/latest>`_.

Prerequisites
=============

* ``UcsSdk`` is a python package version of XML API sdk available to
  manage Cisco UCS Managed B/C-series servers.

  Install ``UcsSdk`` [1]_ module on the Ironic conductor node.
  Required version is 0.8.2.2::

   $ pip install "UcsSdk==0.8.2.2"

Tested Platforms
~~~~~~~~~~~~~~~~
This driver works on Cisco UCS Manager Managed B/C-series servers.
It has been tested with the following servers:

UCS Manager version: 2.2(1b), 2.2(3d).

* UCS B22M, B200M3
* UCS C220M3.

All the Cisco UCS B/C-series servers managed by UCSM 2.1 or later are supported
by this driver.

Configuring and Enabling the driver
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
1. Add ``cisco-ucs-managed`` to the ``enabled_hardware_types`` in
   ``/etc/ironic/ironic.conf``.  For example::

    enabled_hardware_types = ipmi,cisco-ucs-managed

2. Restart the Ironic conductor service::

    service ironic-conductor restart

Registering UCS node in Ironic
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Nodes configured for UCS driver should have the ``driver`` property set to
``cisco-ucs-managed``.  The following configuration values are also required in
``driver_info``:

- ``ucs_address``: IP address or hostname of the UCS Manager
- ``ucs_username``: UCS Manager login user name with administrator or
   server_profile privileges.
- ``ucs_password``: UCS Manager login password for the above UCS Manager user.
- ``deploy_kernel``: The Glance UUID of the deployment kernel.
- ``deploy_ramdisk``: The Glance UUID of the deployment ramdisk.
- ``ucs_service_profile``: Distinguished name(DN) of service_profile being enrolled.

The following sequence of commands can be used to enroll a UCS node.

* Create Node::

    openstack baremetal node create --driver cisco-ucs-managed \
        --driver-info ucs_address=<UCS Manager hostname/ip-address> \
        --driver-info ucs_username=<ucsm_username> \
        --driver-info ucs_password=<ucsm_password> \
        --driver-info ucs_service_profile=<service_profile_dn_being_enrolled> \
        --driver-info deploy_kernel=<glance_uuid_of_deploy_kernel> \
        --driver-info deploy_ramdisk=<glance_uuid_of_deploy_ramdisk> \
        --property cpus=<number_of_cpus> \
        --property memory_mb=<memory_size_in_MB> \
        --property local_gb=<local_disk_size_in_GB> \
        --property cpu_arch=<cpu_arch>

  The above command 'openstack baremetal node create' will return UUID of the
  node, which is the value of $NODE in the following command.

* Associate port with the node created::

    openstack baremetal port create --node $NODE <MAC_address_of_Ucs_server's_NIC>

References
==========
.. [1] UcsSdk - https://pypi.org/project/UcsSdk
