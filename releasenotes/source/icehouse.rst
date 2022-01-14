===============================
Icehouse (2014.1) Release Notes
===============================

Icehouse is the first release of the Ironic project that should be considered "a stable beta." Since there are no prior releases, this highlights the most significant difference between Ironic and nova-baremetal, and lists the major known issues at the time of the Icehouse release.

Features
========

* Nodes are distributed using a consistent hash ring. Conductors automatically register/de-register on startup/shutdown. Operations are distributed automatically across the set of available conductors, with shared locking to prevent multiple conductors working on the same node at once. The hash ring rebalances automatically when conductors join/leave the cluster.
* Heterogeneous hardware support. Multiple ironic-conductor services can be run in the same cluster. Each conductor loads drivers via python entrypoints, and does not necessarily need to load the same drivers as any other conductor service. Requests to manage hardware nodes will be routed to the appropriate conductor according to the node's "driver" property.
  * Note: this does not refer to running nova-compute with multiple compute_drivers in a single AZ.
* API exposes list of available drivers. The API exposes a list of supported drivers and the names of conductor hosts which provide service for them.
* Maintenance mode allows an operator to take a node out of service (hide it from Nova) temporarily, eg. while performing some necessary maintenance task on it.
* Hardware power state is periodically sync'd. By default, a periodic task will check the power state of all nodes, and force unprovisioned nodes' power status to OFF. Nodes whose state can not be checked / synced will be put in maintenance mode after a configurable number of retries.

Known Issues
============

* The Nova "ironic" driver is not present in the Nova code base. Ironic must be installed (but not necessarily run) on the nova-compute hosts to provide the necessary libraries.
* Serial-over-LAN console is not supported.None of the drivers in the Icehouse release support serial console, and the REST API is likely to change during Juno.
* IPMI passwords are visible to users with cloud admin privileges, via Ironic's API.
* Conductor services log an exception trace at startup if the python-seamicroclient library is not present. This can be safely ignored if you are not using the seamicro driver.
* Nova does not pass ephemeral partition specifications to Ironic, even though the Ironic PXE driver supports ephemeral partitioning.
* nova rebuild is not supported by the nova.virt.ironic driver.
* API requests are not translated based on Accept-Language header.

Upgrade Notes
=============

No tools are provided for a migration from nova-baremetal to Ironic at this time.

As there was no prior release of Ironic, no version upgrade is possible.
