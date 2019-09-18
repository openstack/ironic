.. _rescue:

===========
Rescue Mode
===========

Overview
========

The Bare Metal Service supports putting nodes in rescue mode using hardware
types that support rescue interfaces. The hardware types utilizing
ironic-python-agent with ``PXE``/``Virtual Media`` based boot interface can
support rescue operation when configured appropriately.

.. note::
   The rescue operation is currently supported only when tenant networks use
   DHCP to obtain IP addresses.

Rescue operation can be used to boot nodes into a rescue ramdisk so that the
``rescue`` user can access the node, in order to provide the ability to
access the node in case access to OS is not possible.
For example, if there is a need to perform manual password reset or data
recovery in the event of some failure, rescue operation can be used.

Configuring The Bare Metal Service
==================================

Configure the Bare Metal Service appropriately so that the service has the
information needed to boot the ramdisk before a user tries to initiate rescue
operation. This will differ somewhat between different deploy environments,
but an example of how to do this is outlined below:

#. Create and configure ramdisk that supports rescue operation.
   Please see :doc:`/install/deploy-ramdisk` for detailed instructions to
   build a ramdisk.

#. Configure a network to use for booting nodes into the rescue ramdisk in
   neutron, and note the UUID or name of this network. This is required if
   you're using the neutron DHCP provider and have Bare Metal Service
   managing ramdisk booting (the default). This can be the same network as
   your cleaning or tenant network (for flat network).
   For an example of how to configure new networks with Bare Metal Service,
   see the :doc:`/install/configure-networking` documentation.

#. Add the unique name or UUID of your rescue network to ``ironic.conf``:

   .. code-block:: ini

       [neutron]
       rescuing_network=<RESCUE_UUID_OR_NAME>

   .. note::
      This can be set per node via driver_info['rescuing_network']

#. Restart the ironic conductor service.

#. Specify a rescue kernel and ramdisk or rescue ISO compatible with the
   node's driver for pxe based boot interface or virtual-media based boot
   interface respectively.

   Example for pxe based boot interface:

   .. code-block:: console

       openstack baremetal node set $NODE_UUID \
           --driver-info rescue_ramdisk=$RESCUE_INITRD_UUID \
           --driver-info rescue_kernel=$RESCUE_VMLINUZ_UUID

   See :doc:`/install/configure-glance-images` for details. If you are not
   using Image service, it is possible to provide images to Bare Metal
   service via hrefs.

After this, The Bare Metal Service should be ready for ``rescue`` operation.
Test it out by attempting to rescue an active node and connect to the instance
using ssh, as given below:

.. code-block:: console

    openstack baremetal node rescue $NODE_UUID \
        --rescue-password <PASSWORD> --wait

    ssh rescue@$INSTANCE_IP_ADDRESS

To move a node back to active state after using rescue mode you can
use ``unrescue``. Please unmount any filesystems that were manually mounted
before proceeding with unrescue. The node unrescue can be done as given below:

.. code-block:: console

    openstack baremetal node unrescue $NODE_UUID

``rescue`` and ``unrescue`` operations can also be triggered via the Compute
Service using the following commands:

.. code-block:: console

    openstack server rescue --password <password> <server>

    openstack server unrescue <server>
