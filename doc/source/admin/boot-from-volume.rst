.. _boot-from-volume:

================
Boot From Volume
================

Overview
========
The Bare Metal service supports booting from a Cinder iSCSI volume as of the
Pike release. This guide will primarily deal with this use case, but will be
updated as more paths for booting from a volume, such as FCoE, are introduced.

Prerequisites
=============
Currently booting from a volume requires:

- Bare Metal service version 9.0.0
- Bare Metal API microversion 1.33 or later
- A driver that utilizes the `PXE boot mechanism <https://docs.openstack.org/ironic/pike/install/configure-pxe.html>`_.
  Currently booting from a volume is supported by the reference drivers that
  utilize PXE boot mechanisms when iPXE is enabled.
- iPXE is an explicit requirement, as it provides the mechanism that attaches
  and initiates booting from an iSCSI volume.

Conductor Configuration
=======================
In ironic.conf, you can specify a list of enabled storage interfaces. Check
``[DEFAULT]enabled_storage_interfaces`` in your ironic.conf to ensure that
your desired interface is enabled. For example, to enable the ``cinder`` and
``noop`` storage interfaces::

  [DEFAULT]
  enabled_storage_interfaces = cinder,noop

If you want to specify a default storage interface rather than setting the
storage interface on a per node basis, set ``[DEFAULT]default_storage_interface``
in ironic.conf. The ``default_storage_interface`` will be used for any node that
doesn't have a storage interface defined.

Node Configuration
==================

Storage Interface
-----------------
You will need to specify what storage interface the node will use to handle
storage operations. For example, to set the storage interface to ``cinder``
on an existing node::

   openstack --os-baremetal-api-version 1.33 baremetal node set \
             --storage-interface cinder $NODE_UUID

A default storage interface can be specified in ironic.conf. See the
`Conductor Configuration`_ section for details.

iSCSI Configuration
-------------------
In order for a bare metal node to boot from an iSCSI volume, the ``iscsi_boot``
capability for the node must be set to ``True``. For example, if you want to
update an existing node to boot from volume::

   openstack --os-baremetal-api-version 1.33 baremetal node set \
             --property capabilities=iscsi_boot:True $NODE_UUID

You will also need to create a volume connector for the node, so the storage
interface will know how to communicate with the node for storage operation. In
the case of iSCSI, you will need to provide an iSCSI Qualifying Name (IQN)
that is unique to your SAN. For example, to create a volume connector for iSCSI::

   openstack --os-baremetal-api-version 1.33 baremetal volume connector create \
             --node $NODE_UUID --type iqn --connector-id iqn.2017-08.org.openstack.$NODE_UUID
