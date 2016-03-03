.. _CIMC:

============
CIMC drivers
============

Overview
========
The CIMC drivers are targeted for standalone Cisco UCS C series servers.
These drivers enable you to take advantage of CIMC by using the
python SDK.

``pxe_iscsi_cimc`` driver uses PXE boot + iSCSI deploy (just like ``pxe_ipmitool``
driver) to deploy the image and uses CIMC to do all management operations on
the baremetal node (instead of using IPMI).

``pxe_agent_cimc`` driver uses PXE boot + Agent deploy (just like ``agent_ipmitool``
and ``agent_ipminative`` drivers.) to deploy the image and uses CIMC to do all
management operations on the baremetal node (instead of using IPMI). Unlike with
iSCSI deploy in Agent deploy, the ramdisk is responsible for writing the image to
the disk, instead of the conductor.

The CIMC drivers can use the Ironic Inspector service for in-band inspection of
equipment. For more information see the `Ironic Inspector documentation
<http://docs.openstack.org/developer/ironic-inspector/>`_.

Prerequisites
=============

* ``ImcSdk`` is a python SDK for the CIMC HTTP/HTTPS XML API used to control
  CIMC.

Install the ``ImcSdk`` module
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. note::

  Install the ``ImcSdk`` module on the Ironic conductor node. Required version is
  0.7.2.

#. Install it::

   $ pip install "ImcSdk>=0.7.2"

Tested Platforms
~~~~~~~~~~~~~~~~
This driver works with UCS C-Series servers and has been tested with:

* UCS C240M3S

Configuring and Enabling the driver
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
1. Add ``pxe_iscsi_cimc`` and/or ``pxe_agent_cimc`` to the list of ``enabled_drivers`` in
   ``/etc/ironic/ironic.conf``.  For example::

    enabled_drivers = pxe_ipmitool,pxe_iscsi_cimc,pxe_agent_cimc

2. Restart the Ironic conductor service:

   For Ubuntu/Debian systems::

      $ sudo service ironic-conductor restart

   or for RHEL/CentOS/Fedora::

      $ sudo systemctl restart openstack-ironic-conductor

Registering CIMC Managed UCS node in Ironic
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Nodes configured for CIMC driver should have the ``driver`` property set to
``pxe_iscsi_cimc`` or ``pxe_agent_cimc``.  The following configuration values are
also required in ``driver_info``:

- ``cimc_address``: IP address or hostname for CIMC
- ``cimc_username``: CIMC login user name
- ``cimc_password``: CIMC login password for the above CIMC user.
- ``deploy_kernel``: Identifier for the deployment kernel e.g. a Glance UUID
- ``deploy_ramdisk``: Identifier for the deployment ramdisk e.g. a Glance UUID

The following sequence of commands can be used to enroll a UCS Standalone node.

  Create Node::

    ironic node-create -d <pxe_iscsi_cimc OR pxe_agent_cimc> -i cimc_address=<CIMC hostname OR ip-address> -i cimc_username=<cimc_username> -i cimc_password=<cimc_password> -i deploy_kernel=<glance_uuid_of_deploy_kernel> -i deploy_ramdisk=<glance_uuid_of_deploy_ramdisk> -p cpus=<number_of_cpus> -p memory_mb=<memory_size_in_MB> -p local_gb=<local_disk_size_in_GB> -p cpu_arch=<cpu_arch>

  The above command 'ironic node-create' will return UUID of the node, which is the value of $NODE in the following command.

  Associate port with the node created::

    ironic port-create -n $NODE -a <MAC_address_of_Ucs_server's_NIC>

For more information about enrolling nodes see "Enrolling a node" in the :ref:`install-guide`
