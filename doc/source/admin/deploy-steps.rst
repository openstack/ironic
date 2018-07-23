============
Deploy steps
============

Overview
========

Node deployment is performed by the Bare Metal service to prepare a node for
use by a workload.  The exact work flow used depends on a number of factors,
including the hardware type and interfaces assigned to a node.

Customizing deployment
======================

The Bare Metal service implements deployment by collecting a list of deploy
steps to perform on a node from the Power, Deploy, Management, BIOS, and RAID
interfaces of the driver assigned to the node. These steps are then ordered by
priority and executed on the node when the node is moved to the ``deploying``
state.

Nodes move to the ``deploying`` state when attempting to move to the ``active``
state (when the hardware is prepared for use by a workload).  For a full
understanding of all state transitions into deployment, please see
:ref:`states`.

The Bare Metal service added support for deploy steps in the Rocky release.

Deploy steps
------------

Deploy steps are ordered from higher to lower priority, where a larger integer
is a higher priority. If the same priority is used by deploy steps on different
interfaces, the following resolution order is used: Power, Management, Deploy,
BIOS, and RAID interfaces.

FAQ
===

What deploy step is running?
----------------------------
To check what deploy step the node is performing or attempted to perform and
failed, run the following command; it will return the value in the node's
``driver_internal_info`` field::

    openstack baremetal node show $node_ident -f value -c driver_internal_info

The ``deploy_steps`` field will contain a list of all remaining steps with
their priorities, and the first one listed is the step currently in progress or
that the node failed before going into ``deploy failed`` state.

Troubleshooting
===============
If deployment fails on a node, the node will be put into the ``deploy failed``
state until the node is deprovisioned.  A deprovisioned node is moved to the
``available`` state after the cleaning process has been performed successfully.

Strategies for determining why a deploy step failed include checking the ironic
conductor logs, checking logs from the ironic-python-agent that have been
stored on the ironic conductor, or performing general hardware troubleshooting
on the node.
