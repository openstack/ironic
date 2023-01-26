.. _retirement:

===============
Node retirement
===============

Overview
========

Retiring nodes is a natural part of a server’s life cycle, for
instance when the end of the warranty is reached and the physical
space is needed for new deliveries to install replacement capacity.

However, depending on the type of the deployment, removing nodes
from service can be a full workflow by itself as it may include
steps like moving applications to other hosts, cleaning sensitive
data from disks or the BMC, or tracking the dismantling of servers
from their racks.

Ironic provides some means to support such workflows by allowing
to tag nodes as ``retired`` which will prevent any further
scheduling of instances, but will still allow for other operations,
such as cleaning, to happen (this marks an important difference to
nodes which have the ``maintenance`` flag set).

Requirements
============

The use of the retirement feature requires that automated cleaning
be enabled. The default ``[conductor]automated_clean`` setting must
not be disabled as the retirement feature is only engaged upon
the completion of cleaning as it sets forth the expectation of removing
sensitive data from a node.

If you're uncomfortable with full cleaning, but want to make use of the
the retirement feature, a compromise may be to explore use of metadata
erasure, however this will leave additional data on disk which you may
wish to erase completely. Please consult the configuration for the
``[deploy]erase_devices_metadata_priority`` and
``[deploy]erase_devices_priority`` settings, and do note that
clean steps can be manually invoked through manual cleaning should you
wish to trigger the ``erase_devices`` clean step to completely wipe
all data from storage devices. Alternatively, automated cleaning can
also be enabled on an individual node level using the
``baremetal node set --automated-clean <node_id>`` command.

How to use
==========

When it is known that a node shall be retired, set the ``retired``
flag on the node with::

  baremetal node set --retired node-001

This can be done irrespective of the state the node is in, so in
particular while the node is ``active``.

.. NOTE::
   An exception are nodes which are in ``available``. For backwards
   compatibility reasons, these nodes need to be moved to
   ``manageable`` first. Trying to set the ``retired`` flag for
   ``available`` nodes will result in an error.

Optionally, a reason can be specified when a node is retired, e.g.::

  baremetal node set --retired node-001 \
    --retired-reason "End of warranty for delivery abc123"

Upon instance deletion, an ``active`` node with the ``retired`` flag
set will not move to ``available``, but to ``manageable``. The node
will hence not be eligible for scheduling of new instances.

Equally, nodes with ``retired`` set to True cannot move from ``manageable``
to ``available``: the ``provide`` verb is blocked. This is to prevent
accidental re-use of nodes tagged for removal from the fleet. In order
to move these nodes to ``available`` none the less, the ``retired`` field
needs to be removed first. This can be done via::

  baremetal node unset --retired node-001

In order to facilitate the identification of nodes marked for retirement,
e.g. by other teams, ironic also allows to list all nodes which have the
``retired`` flag set::

  baremetal node list --retired
