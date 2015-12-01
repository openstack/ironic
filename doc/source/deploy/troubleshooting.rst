.. _troubleshooting:

======================
Troubleshooting Ironic
======================

Nova returns "No valid host was found" Error
============================================

Sometimes Nova Conductor log file "nova-conductor.log" or a message returned
from Nova API contains the following error::

    NoValidHost: No valid host was found. There are not enough hosts available.

"No valid host was found" means that the Nova Scheduler could not find a bare
metal node suitable for booting the new instance.

This in turn usually means some mismatch between resources that Nova expects
to find and resources that Ironic advertised to Nova.

A few things should be checked in this case:

#. Inspection should have succeeded for you before, or you should have
   entered the required Ironic node properties manually. For each node with
   available state in ``ironic node-list --provision-state available`` use
   ::

    ironic node-show <IRONIC-NODE-UUID>

   and make sure that ``properties`` JSON field has valid values for keys
   ``cpus``, ``cpu_arch``, ``memory_mb`` and ``local_gb``.

#. The Nova flavor that you are using does not match any properties of the
   available Ironic nodes. Use
   ::

    nova flavor-show <FLAVOR NAME>

   to compare. If you're using exact match filters in Nova Scheduler, please
   make sure the flavor and the node properties match exactly. Regarding
   the extra specs in flavor, you should make sure they map to
   ``node.properties['capabilities']``.

#. Make sure that enough nodes are in ``available`` state according to
   ``ironic node-list --provision-state available``.

#. Make sure nodes you're going to deploy to are not in maintenance mode.
   Again, use ``ironic node-list`` to check. A node automatically going to
   maintenance mode usually means wrong power credentials for this node. Check
   them and then remove maintenance mode::

    ironic node-set-maintenance <IRONIC-NODE-UUID> off

#. After making changes to nodes in Ironic, it takes time for those changes
   to propagate from Ironic to Nova.
   Check that
   ::

    nova hypervisor-stats

   correctly shows total amount of resources in your system. You can also
   check ``nova hypervisor-list`` to see the status of individual Ironic
   nodes as reported to Nova. And you can correlate the Nova "hypervisor
   hostname" to the Ironic node UUID.

#. If none of the above helped, check Ironic conductor log carefully to see
   if there are any conductor-related errors which are the root cause for
   "No valid host was found". If there are any "Error in deploy of node
   <IRONIC-NODE-UUID>: [Errno 28] ..." error messages in Ironic conductor
   log, it means the conductor run into a special error during deployment.
   So you can check the log carefully to fix or work around and then try
   again.
