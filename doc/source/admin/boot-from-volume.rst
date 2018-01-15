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
- A driver that utilizes the :doc:`PXE boot mechanism </install/configure-pxe>`.
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

Advanced Topics
===============

Use without the Compute Service
-------------------------------

As discussed in other sections, the Bare Metal service has a concept of a
`connector` that is used to represent an interface that is intended to
be utilized to attach the remote volume.

In addition to the connectors, we have a concept of a `target` that can be
defined via the API. While a user of this feature through the Compute
service would automatically have a new target record created for them,
it is not explicitly required, and can be performed manually.

A target record can be created using a command similar to the example below::

    openstack --os-baremetal-api-version 1.33 baremetal volume target create \
              --node $NODE_UUID --type iscsi --boot-index 0 --volume $VOLUME_UUID

.. Note:: A ``boot-index`` value of ``0`` represents the boot volume for a
          node. As the ``boot-index`` is per-node in sequential order,
          only one boot volume is permitted for each node.

Cinder Multi-attach
-------------------

Volume multi-attach is a function that is commonly performed in computing
clusters where dedicated storage subsystems are utilized. For some time now,
the Block Storage service has supported the concept of multi-attach.
However, the Compute service, as of the Pike release, does not yet have
support to leverage multi-attach. Concurrently, multi-attach requires the
backend volume driver running as part of the Block Storage service to
contain support for multi-attach volumes.

When support for storage interfaces was added to the Bare Metal service,
specifically for the ``cinder`` storage interface, the concept of volume
multi-attach was accounted for, however has not been fully tested,
and is unlikely to be fully tested until there is Compute service integration
as well as volume driver support.

The data model for storage of volume targets in the Bare Metal service
has no constraints on the same target volume from being utilized.
When interacting with the Block Storage service, the Bare Metal service
will prevent the use of volumes that are being reported as ``in-use``
if they do not explicitly support multi-attach.
