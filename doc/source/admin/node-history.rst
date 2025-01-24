.. _node-history:

============
Node History
============

Overview
========
Ironic keeps a record of node error events in node history. This allows
operators to track frequent failures and get additional context when
troubleshooting failures.

How it works
============

Anytime a node would have it's ``last_error`` populated, an entry is added
to the history of the node containing severity of and details about the
failure.

Node history can be completely disabled by setting
:oslo.config:option:`conductor.node_history` to ``False``; it is enabled
by default.

Since node history can grow unbounded over time, by default Ironic
is configured to prune the data; this behavior is configurable with
the following settings:

- :oslo.config:option:`conductor.node_history_max_entries`
- :oslo.config:option:`conductor.node_history_cleanup_interval`
- :oslo.config:option:`conductor.node_history_cleanup_batch_count`
- :oslo.config:option:`conductor.node_history_minimum_days`

Client usage
============
The baremetal CLI has full support for node history.

To view the list of entries in history for a node:
``baremetal node history list $node``.

To see a specific node history entry you want to see in detail:
``baremetal node history get $node $eventId``.

Node history entries cannot be removed manually. Use the configuration
options listed in the previous section to control the automatic pruning
behavior of Ironic.

