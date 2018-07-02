.. _CIMC:

===========
CIMC driver
===========

Overview
========

The ``cisco-ucs-standalone`` hardware type targets standalone Cisco UCS C
series servers. It enables you to take advantage of CIMC by using
the python SDK.

The CIMC hardware type can use the Ironic Inspector service for in-band
inspection of equipment. For more information see the `Ironic Inspector
documentation <https://docs.openstack.org/ironic-inspector/latest>`_.

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
1. Add ``cisco-ucs-standalone`` to ``enabled_hardware_types`` in
   ``/etc/ironic/ironic.conf``.  For example::

    enabled_hardware_types = ipmi,cisco-ucs-standalone

2. Restart the Ironic conductor service:

   For Ubuntu/Debian systems::

      $ sudo service ironic-conductor restart

   or for RHEL/CentOS/Fedora::

      $ sudo systemctl restart openstack-ironic-conductor

Registering CIMC Managed UCS node in Ironic
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Nodes configured for CIMC driver should have the ``driver`` property set to
``cisco-ucs-standalone``.  The following configuration values are also required
in ``driver_info``:

- ``cimc_address``: IP address or hostname for CIMC
- ``cimc_username``: CIMC login user name
- ``cimc_password``: CIMC login password for the above CIMC user.
- ``deploy_kernel``: Identifier for the deployment kernel e.g. a Glance UUID
- ``deploy_ramdisk``: Identifier for the deployment ramdisk e.g. a Glance UUID

The following sequence of commands can be used to enroll a UCS Standalone node.

* Create Node::

    openstack baremetal node create --driver cisco-ucs-standalone \
      --driver-info cimc_address=<CIMC hostname OR ip-address> \
      --driver-info cimc_username=<cimc_username> \
      --driver-info cimc_password=<cimc_password> \
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

For more information about enrolling nodes see :ref:`enrollment` in the install guide.
