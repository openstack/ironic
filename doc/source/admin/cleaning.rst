.. _cleaning:

=============
Node cleaning
=============

Overview
========
Ironic provides two modes for node cleaning: ``automated`` and ``manual``.

``Automated cleaning`` is automatically performed before the first
workload has been assigned to a node and when hardware is recycled from
one workload to another.

``Manual cleaning`` must be invoked by the operator.


.. _automated_cleaning:

Automated cleaning
==================

When hardware is recycled from one workload to another, ironic performs
automated cleaning on the node to ensure it's ready for another workload. This
ensures the tenant will get a consistent bare metal node deployed every time.

Ironic implements automated cleaning by collecting a list of cleaning steps
to perform on a node from the Power, Deploy, Management, BIOS, and RAID
interfaces of the driver assigned to the node. These steps are then ordered by
priority and executed on the node when the node is moved to ``cleaning`` state,
if automated cleaning is enabled.

With automated cleaning, nodes move to ``cleaning`` state when moving from
``active`` -> ``available`` state (when the hardware is recycled from one
workload to another). Nodes also traverse cleaning when going from
``manageable`` -> ``available`` state (before the first workload is
assigned to the nodes). For a full understanding of all state transitions
into cleaning, please see :ref:`states`.

Ironic added support for automated cleaning in the Kilo release.

.. _enabling-cleaning:

Enabling automated cleaning
---------------------------

To enable automated cleaning, ensure that your ironic.conf is set as follows:

.. code-block:: ini

  [conductor]
  automated_clean=true

This will enable the default set of cleaning steps, based on your hardware and
ironic hardware types used for nodes. This includes, by default, erasing all
of the previous tenant's data.

You may also need to configure a `Cleaning Network`_.

Cleaning steps
--------------

Cleaning steps used for automated cleaning are ordered from higher to lower
priority, where a larger integer is a higher priority. In case of a conflict
between priorities across interfaces, the following resolution order is used:
Power, Management, Deploy, BIOS, and RAID interfaces.

You can skip a cleaning step by setting the priority for that cleaning step
to zero or 'None'.

You can reorder the cleaning steps by modifying the integer priorities of the
cleaning steps.

See `How do I change the priority of a cleaning step?`_ for more information.

Storage cleaning options
------------------------

Clean steps specific to storage are ``erase_devices``,
``erase_devices_metadata`` and (added in Yoga) ``erase_devices_express``.

``erase_devices`` aims to ensure that the data is removed in the most secure
way available. On devices that support hardware assisted secure erasure
(many NVMe and some ATA drives) this is the preferred option. If
hardware-assisted secure erasure is not available and if
``[deploy]/continue_if_disk_secure_erase_fails`` is set to ``True``, cleaning
will fall back to using ``shred`` to overwrite the contents of the device.
Otherwise cleaning will fail. It is important to note that ``erase_devices``
may take a very long time (hours or even days) to complete, unless fast,
hardware assisted data erasure is supported by all the devices in a system.
Generally, it is very difficult (if possible at all) to recover data after
performing cleaning with ``erase_devices``.

``erase_devices_metadata`` clean step doesn't provide as strong assurance
of irreversible destruction of data as ``erase_devices``. However, it has the
advantage of a reasonably quick runtime (seconds to minutes). It operates by
destroying metadata of the storage device without erasing every bit of the
data itself. Attempts of restoring data after running
``erase_devices_metadata`` may be successful but would certainly require
relevant expertise and specialized tools.

Lastly, ``erase_devices_express`` combines some of the perks of both
``erase_devices`` and ``erase_devices_metadata``. It attempts to utilize
hardware assisted data erasure features if available (currently only NVMe
devices are supported). In case hardware-asssisted data erasure is not
available, it falls back to metadata erasure for the device (which is
identical to ``erase_devices_metadata``). It can be considered a
time optimized mode of storage cleaning, aiming to perform as thorough
data erasure as it is possible within a short period of time.
This clean step is particularly well suited for environments with hybrid
NVMe-HDD storage configuration as it allows fast and secure erasure of data
stored on NVMes combined with equally fast but more basic metadata-based
erasure of data on HDDs.
``erase_devices_express`` is disabled by default. In order to use it, the
following configuration is recommended.

.. code-block:: ini

    [deploy]/erase_devices_priority=0
    [deploy]/erase_devices_metadata_priority=0
    [conductor]/clean_step_priority_override=deploy.erase_devices_express:5

This ensures that ``erase_devices`` and ``erase_devices_metadata`` are
disabled so that storage is not cleaned twice and then assigns a non-zero
priority to ``erase_devices_express``, hence enabling it. Any non-zero
priority specified in the priority override will work.

Also `[deploy]/enable_nvme_secure_erase` should not be disabled (it is on by default).

.. show-steps::
   :phase: cleaning

.. _manual_cleaning:

Manual cleaning
===============

``Manual cleaning`` is typically used to handle long running, manual, or
destructive tasks that an operator wishes to perform either before the first
workload has been assigned to a node or between workloads. When initiating a
manual clean, the operator specifies the cleaning steps to be performed.
Manual cleaning can only be performed when a node is in the ``manageable``
state. Once the manual cleaning is finished, the node will be put in the
``manageable`` state again.

Ironic added support for manual cleaning in the 4.4 (Mitaka series)
release.

Setup
-----

In order for manual cleaning to work, you may need to configure a
`Cleaning Network`_.

Starting manual cleaning via API
--------------------------------

Manual cleaning can only be performed when a node is in the ``manageable``
state. The REST API request to initiate it is available in API version 1.15 and
higher::

    PUT /v1/nodes/<node_ident>/states/provision

(Additional information is available `here <https://docs.openstack.org/api-ref/baremetal/index.html?expanded=change-node-provision-state-detail#change-node-provision-state>`_.)

This API will allow operators to put a node directly into ``cleaning``
provision state from ``manageable`` state via 'target': 'clean'.
The PUT will also require the argument 'clean_steps' to be specified. This
is an ordered list of cleaning steps. A cleaning step is represented by a
dictionary (JSON), in the form::

  {
      "interface": "<interface>",
      "step": "<name of cleaning step>",
      "args": {"<arg1>": "<value1>", ..., "<argn>": <valuen>}
  }

The 'interface' and 'step' keys are required for all steps. If a cleaning step
method takes keyword arguments, the 'args' key may be specified. It
is a dictionary of keyword variable arguments, with each keyword-argument entry
being <name>: <value>.

If any step is missing a required keyword argument, manual cleaning will not be
performed and the node will be put in ``clean failed`` provision state with an
appropriate error message.

If, during the cleaning process, a cleaning step determines that it has
incorrect keyword arguments, all earlier steps will be performed and then the
node will be put in ``clean failed`` provision state with an appropriate error
message.

An example of the request body for this API::

  {
    "target":"clean",
    "clean_steps": [{
      "interface": "raid",
      "step": "create_configuration",
      "args": {"create_nonroot_volumes": false}
    },
    {
      "interface": "deploy",
      "step": "erase_devices"
    }]
  }

In the above example, the node's RAID interface would configure hardware
RAID without non-root volumes, and then all devices would be erased
(in that order).

Starting manual cleaning via "openstack metal" CLI
------------------------------------------------------

Manual cleaning is available via the ``baremetal node clean``
command, starting with Bare Metal API version 1.15.

The argument ``--clean-steps`` must be specified. Its value is one of:

- a JSON string
- path to a JSON file whose contents are passed to the API
- '-', to read from stdin. This allows piping in the clean steps.
  Using '-' to signify stdin is common in Unix utilities.

The following examples assume that the Bare Metal API version was set via
the ``OS_BAREMETAL_API_VERSION`` environment variable. (The alternative is to
add ``--os-baremetal-api-version 1.15`` to the command.)::

    export OS_BAREMETAL_API_VERSION=1.15

Examples of doing this with a JSON string::

    baremetal node clean <node> \
        --clean-steps '[{"interface": "deploy", "step": "erase_devices_metadata"}]'

    baremetal node clean <node> \
        --clean-steps '[{"interface": "deploy", "step": "erase_devices"}]'

Or with a file::

    baremetal node clean <node> \
        --clean-steps my-clean-steps.txt

Or with stdin::

    cat my-clean-steps.txt | baremetal node clean <node> \
        --clean-steps -

Cleaning Network
================

If you are using the Neutron DHCP provider (the default) you will also need to
ensure you have configured a cleaning network. This network will be used to
boot the ramdisk for in-band cleaning. You can use the same network as your
tenant network. For steps to set up the cleaning network, please see
:ref:`configure-cleaning`.

.. _InbandvsOutOfBandCleaning:

In-band vs out-of-band
======================
Ironic uses two main methods to perform actions on a node: in-band and
out-of-band. Ironic supports using both methods to clean a node.

In-band
-------
In-band steps are performed by ironic making API calls to a ramdisk running
on the node using a deploy interface. Currently, all the deploy interfaces
support in-band cleaning. By default, ironic-python-agent ships with a minimal
cleaning configuration, only erasing disks. However, you can add your own
cleaning steps and/or override default cleaning steps with a custom
Hardware Manager.

Out-of-band
-----------
Out-of-band are actions performed by your management controller, such as IPMI,
iLO, or DRAC. Out-of-band steps will be performed by ironic using a power or
management interface. Which steps are performed depends on the hardware type
and hardware itself.

For Out-of-Band cleaning operations supported by iLO hardware types, refer to
:ref:`ilo_node_cleaning`.

FAQ
===

How are cleaning steps ordered?
-------------------------------
For automated cleaning, cleaning steps are ordered by integer priority, where
a larger integer is a higher priority. In case of a conflict between priorities
across hardware interfaces, the following resolution order is used:

#. Power interface
#. Management interface
#. Deploy interface
#. BIOS interface
#. RAID interface

For manual cleaning, the cleaning steps should be specified in the desired
order.

How do I skip a cleaning step?
------------------------------
For automated cleaning, cleaning steps with a priority of 0 or None are skipped.


How do I change the priority of a cleaning step?
------------------------------------------------
For manual cleaning, specify the cleaning steps in the desired order.

For automated cleaning, it depends on whether the cleaning steps are
out-of-band or in-band.

Most out-of-band cleaning steps have an explicit configuration option for
priority.

Changing the priority of an in-band (ironic-python-agent) cleaning step
requires use of a custom HardwareManager. The only exception is
``erase_devices``, which can have its priority set in ironic.conf. For instance,
to disable erase_devices, you'd set the following configuration option::

  [deploy]
  erase_devices_priority=0

To enable/disable the in-band disk erase using ``ilo`` hardware type, use the
following configuration option::

  [ilo]
  clean_priority_erase_devices=0

The generic hardware manager first identifies whether a device is an NVMe
drive or an ATA drive so that it can attempt a platform-specific secure erase
method. In case of NVMe drives, it tries to perform a secure format operation
by using the ``nvme-cli`` utility. This behavior can be controlled using
the following configuration option (by default it is set to True)::

   [deploy]
   enable_nvme_secure_erase=True


In case of ATA drives, it tries to perform ATA disk erase by using the
``hdparm`` utility.

If neither method is supported, it performs software based disk erase using
the ``shred`` utility.  By default, the number of iterations performed
by ``shred`` for software based disk erase is 1. To configure the number of
iterations, use the following configuration option::

  [deploy]
  erase_devices_iterations=1

Overriding step priority
------------------------

``[conductor]clean_step_priority_override`` is a new configuration option
which allows specifying priority of each step using multiple configuration
values:

.. code-block:: ini

  [conductor]
  clean_step_priority_override=deploy.erase_devices_metadata:123
  clean_step_priority_override=management.reset_bios_to_default:234
  clean_step_priority_override=management.clean_priority_reset_ilo:345

This parameter can be specified as many times as required to define priorities
for several cleaning steps - the values will be combined.

What cleaning step is running?
------------------------------
To check what cleaning step the node is performing or attempted to perform and
failed, run the following command; it will return the value in the node's
``driver_internal_info`` field::

    baremetal node show $node_ident -f value -c driver_internal_info

The ``clean_steps`` field will contain a list of all remaining steps with their
priorities, and the first one listed is the step currently in progress or that
the node failed before going into ``clean failed`` state.

Should I disable automated cleaning?
------------------------------------
Automated cleaning is recommended for ironic deployments, however, there are
some tradeoffs to having it enabled. For instance, ironic cannot deploy a new
instance to a node that is currently cleaning, and cleaning can be a time
consuming process. To mitigate this, we suggest using NVMe drives with support
for NVMe Secure Erase (based on ``nvme-cli`` format command) or ATA drives
with support for cryptographic ATA Security Erase, as typically the
erase_devices step in the deploy interface takes the longest time to complete
of all cleaning steps.

Why can't I power on/off a node while it's cleaning?
----------------------------------------------------
During cleaning, nodes may be performing actions that shouldn't be
interrupted, such as BIOS or Firmware updates. As a result, operators are
forbidden from changing power state via the ironic API while a node is
cleaning.

Advanced topics
===============

Parent Nodes
------------

The concept of a ``parent_node`` is where a node is configured to have a
"parent", and allows for actions upon the parent, to in some cases take into
account child nodes. Mainly, the concept of executing clean steps in relation
to child nodes.

In this context, a child node is primarily intended to be an embedded device
with it's own management controller. For example "SmartNIC's" or Data
Processing Units (DPUs) which may have their own management controller and
power control.

The relationship between a parent node and a child node is established on the child node. Example::

  baremetal node set --parent-node <parent_node_uuid> <child_node_uuid>

Child Node Clean Step Execution
-------------------------------

You can execute steps which perform actions on child nodes. For example,
turn them on (via step ``power_on``), off (via step ``power_off``), or to
signal a BMC controlled reboot (via step ``reboot``).

For example, if you need to explicitly power off child node power, before
performing another step, you can articulate it with a step such as::

    [{
      "interface": "power",
      "step": "power_off",
      "execute_on_child_nodes": True,
      "limit_child_node_execution": ['f96c8601-0a62-4e99-97d6-1e0d8daf6dce']
    },
    {
      "interface": "deploy",
      "step": "erase_devices"
    }]

As one would imagine, this step will power off a singular child node, as
a limit has been expressed to a singular known node, and that child node's
power will be turned off via the management interface. Afterwards, the
``erase_devices`` step will be executed on the parent node.

.. NOTE::
   While the deployment step framework also supports the
   ``execute_on_child_nodes`` and ``limit_child_node_execution`` parameters,
   all of the step frameworks have a fundamental limitation in that child node
   step execution is indended for syncronous actions which do not rely upon
   the ``ironic-python-agent`` running on any child nodes. This constraint may
   be changed in the future.

Troubleshooting
===============
If cleaning fails on a node, the node will be put into ``clean failed`` state.
If the failure happens while running a clean step, the node is also placed in
maintenance mode to prevent ironic from taking actions on the node. The
operator should validate that no permanent damage has been done to the
node and no processes are still running on it before removing the maintenance
mode.

.. note:: Older versions of ironic may put the node to maintenance even when
          no clean step has been running.

Nodes in ``clean failed`` will not be powered off, as the node might be in a
state such that powering it off could damage the node or remove useful
information about the nature of the cleaning failure.

A ``clean failed`` node can be moved to ``manageable`` state, where it cannot
be scheduled by nova and you can safely attempt to fix the node. To move a node
from ``clean failed`` to ``manageable``::

  baremetal node manage $node_ident

You can now take actions on the node, such as replacing a bad disk drive.

Strategies for determining why a cleaning step failed include checking the
ironic conductor logs, viewing logs on the still-running ironic-python-agent
(if an in-band step failed), or performing general hardware troubleshooting on
the node.

When the node is repaired, you can move the node back to ``available`` state,
to allow it to be scheduled by nova.

::

  # First, move it out of maintenance mode
  baremetal node maintenance unset $node_ident

  # Now, make the node available for scheduling by nova
  baremetal node provide $node_ident

The node will begin automated cleaning from the start, and move to
``available`` state when complete.
