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

How to use
==========

When it is known that a node shall be retired, set the ``retired``
flag on the node with::

  openstack baremetal node set --retired node-001

This can be done irrespective of the state the node is in, so in
particular while the node is ``active``.

.. NOTE::
   An exception are nodes which are in ``available``. For backwards
   compatibility reasons, these nodes need to be moved to
   ``manageable`` first. Trying to set the ``retired`` flag for
   ``available`` nodes will result in an error.

Optionally, a reason can be specified when a node is retired, e.g.::

  openstack baremetal node set --retired node-001 \
    --retired-reason "End of warranty for delivery abc123"

Upon instance deletion, an ``active`` node with the ``retired`` flag
set will not move to ``available``, but to ``manageable``. The node
will hence not be eligible for scheduling of new instances.

Equally, nodes with ``retired`` set to True cannot move from ``manageable``
to ``available``: the ``provide`` verb is blocked. This is to prevent
accidental re-use of nodes tagged for removal from the fleet. In order
to move these nodes to ``available`` none the less, the ``retired`` field
needs to be removed first. This can be done via::

  openstack baremetal node unset --retired node-001

In order to facilitate the identification of nodes marked for retirement,
e.g. by other teams, ironic also allows to list all nodes which have the
``retired`` flag set::

  openstack baremetal node list --retired
