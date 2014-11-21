.. _SeaMicro:

===============
SeaMicro driver
===============

Overview
========
The SeaMicro power driver enables you to take advantage of power cycle
management of servers (nodes) within the SeaMicro chassis. The SeaMicro
driver is targeted for SeaMicro Fabric Compute systems.

Prerequisites
=============

* ``python-seamicroclient`` is a python package which contains a set of modules
  for managing SeaMicro Fabric Compute systems.

  Install ``python-seamicroclient`` [1]_ module on the Ironic conductor node.
  Minimum version required is 0.2.1.::

   $ pip install "python-seamicroclient>=0.2.1"

Drivers
=======

pxe_seamicro driver
^^^^^^^^^^^^^^^^^^^

Overview
~~~~~~~~
``pxe_seamicro`` driver uses PXE/iSCSI (just like ``pxe_ipmitool`` driver) to
deploy the image and uses SeaMicro to do all management operations on the
baremetal node (instead of using IPMI).

Target Users
~~~~~~~~~~~~
* Users who want to use PXE/iSCSI for deployment in their environment.
* Users who want to use SeaMicro Fabric Compute systems.

Tested Platforms
~~~~~~~~~~~~~~~~
This driver works on SeaMicro Fabric Compute system.
It has been tested with the following servers:

* SeaMicro SM15000-XN
* SeaMicro SM15000-OP

Requirements
~~~~~~~~~~~~
None.

Configuring and Enabling the driver
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
1. Prepare an ISO deploy ramdisk image from ``diskimage-builder`` [2]_.

   The below command creates files named ``deploy-ramdisk.kernel`` and
   ``deploy-ramdisk.initramfs`` in the current working directory::

    <path_to_diskimage_builder>/bin/ramdisk-image-create -o deploy-ramdisk ubuntu deploy-ironic

2. Upload these images to Glance::

    glance image-create --name deploy-ramdisk.kernel --disk-format aki --container-format aki < deploy-ramdisk.kernel
    glance image-create --name deploy-ramdisk.initramfs --disk-format ari --container-format ari < deploy-ramdisk.initramfs

3. Add ``pxe_seamicro`` to the list of ``enabled_drivers`` in
   ``/etc/ironic/ironic.conf``.  For example::

    enabled_drivers = pxe_ipmitool,pxe_seamicro

4. Restart the Ironic conductor service::

    service ironic-conductor restart

Registering SeaMicro node in Ironic
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Nodes configured for SeaMicro driver should have the ``driver`` property set to
``pxe_seamicro``.  The following configuration values are also required in
``driver_info``:

- ``seamicro_api_endpoint``: IP address or hostname of the SeaMicro with valid
  URL as http://<IP_address/hostname>/v2.0
- ``seamicro_server_id``: SeaMicro Server ID. Expected format is <int>/<int>
- ``seamicro_username``: SeaMicro Username with administrator privileges.
- ``seamicro_password``: Password for the above SeaMicro user.
- ``pxe_deploy_kernel``: The Glance UUID of the deployment kernel.
- ``pxe_deploy_ramdisk``: The Glance UUID of the deployment ramdisk.
- ``seamicro_api_version``: (optional) SeaMicro API Version defaults to "2".
- ``seamicro_terminal_port``: (optional) Node's UDP port for console access.
  Any unused port on the Ironic conductor node may be used.

The following sequence of commands can be used to enroll a SeaMicro node and
boot an instance on it:

  Create nova baremetal flavor corresponding to SeaMicro server's config::

    nova flavor-create baremetal auto <memory_size_in_MB> <disk_size_in_GB> <number_of_cpus>

  Create Node::

    ironic node-create -d pxe_seamicro -i seamicro_api_endpoint=https://<seamicro_ip_address>/ -i seamicro_server_id=<seamicro_server_id> -i seamicro_username=<seamicro_username> -i seamicro_password=<seamicro_password> -i seamicro_api_version=<seamicro_api_version> -i seamicro_terminal_port=<seamicro_terminal_port> -i pxe_deploy_kernel=<glance_uuid_of_pxe_deploy_kernel> -i pxe_deploy_ramdisk=<glance_uuid_of_deploy_ramdisk> -p cpus=<number_of_cpus> -p memory_mb=<memory_size_in_MB> -p local_gb=<local_disk_size_in_GB> -p cpu_arch=<cpu_arch>

  Associate port with the node created::

    ironic port-create -n $NODE -a <MAC_address_of_SeaMicro_server's_NIC>

  Associate properties with the flavor::

    nova flavor-key baremetal set "cpu_arch"=<cpu_arch>

  Boot the Instance::

    nova boot --flavor baremetal --image test-image instance-1

References
==========
.. [1] Python-seamicroclient - https://pypi.python.org/pypi/python-seamicroclient
.. [2] DiskImage-Builder - https://github.com/openstack/diskimage-builder
