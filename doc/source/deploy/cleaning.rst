.. _cleaning:

=============
Node cleaning
=============

Overview
========
When hardware is recycled from one workload to another, ironic performs
cleaning on the node to ensure it's ready for another workload. This ensures
the tenant will get a consistent bare metal node deployed every time.

Ironic implements cleaning by collecting a list of steps to perform on a node
from each Power, Deploy, and Management driver assigned to the node. These
steps are then arranged by priority and executed on the node when it is moved
to cleaning state, if cleaning is enabled.

Typically, nodes move to cleaning state when moving from active -> available.
Nodes also traverse cleaning when going from manageable -> available. For a
full understanding of all state transitions into cleaning, please see
:ref:`states`.

Ironic added support for cleaning nodes in the Kilo release.


Enabling cleaning
=================
To enable cleaning, ensure your ironic.conf is set as follows: ::

  [conductor]
  clean_nodes=true

This will enable the default set of steps, based on your hardware and ironic
drivers. If you're using an agent_* driver, this includes, by default, erasing
all of the previous tenant's data.

If you are using the Neutron DHCP provider (the default) you will also need to
ensure you have configured a cleaning network. This network will be used to
boot the ramdisk for in-band cleaning. You can use the same network as your
tenant network. For steps to set up the cleaning network, please see
:ref:`CleaningNetworkSetup`.

.. _InbandvsOutOfBandCleaning:

In-band vs out-of-band
======================
Ironic uses two main methods to perform actions on a node: in-band and
out-of-band. Ironic supports using both methods to clean a node.

In-band
-------
In-band steps are performed by ironic making API calls to a ramdisk running
on the node using a Deploy driver. Currently, only the ironic-python-agent
ramdisk used with an agent_* driver supports in-band cleaning. By default,
ironic-python-agent ships with a minimal cleaning configuration, only erasing
disks. However, with this ramdisk, you can add your own cleaning steps and/or
override default cleaning steps with a custom Hardware Manager.

There is currently no support for in-band cleaning using the ironic pxe
ramdisk.

Out-of-band
-----------
Out-of-band are actions performed by your management controller, such as IPMI,
iLO, or DRAC. Out-of-band steps will be performed by ironic using a Power or
Management driver. Which steps are performed depends on the driver and hardware.

For Out-of-Band cleaning operations supported by iLO drivers, refer to
:ref:`ilo_node_cleaning`.

FAQ
===

How are cleaning steps ordered?
-------------------------------
Cleaning steps are ordered by integer priority, where a larger integer is a
higher priority. In case of a conflict between priorities across drivers,
the following resolution order is used: Power, Management, Deploy.

How do I skip a cleaning step?
------------------------------
Cleaning steps with a priority of 0 or None are skipped.

How do I change the priority of a cleaning step?
------------------------------------------------
Most out-of-band cleaning steps have an explicit configuration option for
priority.

Changing the priority of an in-band (ironic-python-agent) cleaning step
currently requires use of a custom HardwareManager. The only exception is
erase_devices, which can have its priority set in ironic.conf. For instance,
to disable erase_devices, you'd use the following config::

  [deploy]
  erase_devices_priority=0

To enable/disable the in-band disk erase using ``agent_ilo`` driver, use the
following config::

  [ilo]
  clean_priority_erase_devices=0

Generic hardware manager first tries to perform ATA disk erase by using
``hdparm`` utility.  If ATA disk erase is not supported, it performs software
based disk erase using ``shred`` utility.  By default, the number of iterations
performed by ``shred`` for software based disk erase is 1.  To configure
the number of iterations, use the following config::

  [deploy]
  erase_devices_iterations=1


What cleaning step is running?
------------------------------
To check what cleaning step the node is performing or attempted to perform and
failed, either query the node endpoint for the node or run ``ironic node-show
$node_ident`` and look in the `internal_driver_info` field. The `clean_steps`
field will contain a list of all remaining steps with their priority, and the
first one listed is the step currently in progress or that the node failed
before going into cleanfail state.

Should I disable cleaning?
--------------------------
Cleaning is recommended for ironic deployments, however, there are some
tradeoffs to having it enabled. For instance, ironic cannot deploy a new
instance to a node that is currently cleaning, and cleaning can be a time
consuming process. To mitigate this, we suggest using disks with support for
cryptographic ATA Security Erase, as typically the erase_devices step in the
deploy driver takes the longest time to complete of all cleaning steps.

Why can't I power on/off a node while it's cleaning?
----------------------------------------------------
During cleaning, nodes may be performing actions that shouldn't be
interrupted, such as BIOS or Firmware updates. As a result, operators are
forbidden from changing power state via the ironic API while a node is
cleaning.


Troubleshooting
===============
If cleaning fails on a node, the node will be put into cleanfail state and
placed in maintenance mode, to prevent ironic from taking actions on the
node.

Nodes in cleanfail will not be powered off, as the node might be in a state
such that powering it off could damage the node or remove useful information
about the nature of the cleaning failure.

A cleanfail node can be moved to manageable state, where they cannot be
scheduled by nova and you can safely attempt to fix the node. To move a node
from cleanfail to manageable: ``ironic node-set-provision-state manage``.
You can now take actions on the node, such as replacing a bad disk drive.

Strategies for determining why a cleaning step failed include checking the
ironic conductor logs, viewing logs on the still-running ironic-python-agent
(if an in-band step failed), or performing general hardware troubleshooting on
the node.

When the node is repaired, you can move the node back to available state, to
allow it to be scheduled by nova.

::

  # First, move it out of maintenance mode
  ironic node-set-maintenance $node_ident false

  # Now, make the node available for scheduling by nova
  ironic node-set-provision-state $node_ident provide

The node will begin cleaning from the start, and move to available state
when complete.
