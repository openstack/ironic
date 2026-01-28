.. _health-monitoring:

======================
Node Health Monitoring
======================

Overview
========

Ironic can monitor and report the hardware health status of baremetal nodes
by querying the Baseboard Management Controller (BMC). This provides operators
with visibility into potential hardware issues before they cause failures.

The health status is stored in the node's ``health`` field and can have one
of the following values:

* **OK** - Hardware is functioning normally with no issues detected.
* **Warning** - Hardware has non-critical issues that may require attention.
* **Critical** - Hardware has critical issues requiring immediate attention.
* **None** - Health status is not available (driver doesn't support it or
  BMC didn't report it).

How it works
============

Health monitoring integrates with Ironic's existing power state synchronization
cycle. When the conductor queries a node's power state, it also retrieves the
hardware health status if the driver supports it.

The health status is cached in the node's database record and updated
periodically along with power state. No separate polling interval is required.

Drivers that do not implement health monitoring are silently skipped - nodes
managed by such drivers will simply have a ``None`` health value.

Configuration
=============

Health monitoring is **enabled by default**. To disable it, set the following
in your Ironic configuration:

.. code-block:: ini

   [conductor]
   enable_health_monitoring = False

Supported Drivers
=================

Currently, the following drivers support health monitoring:

* **Redfish** - Retrieves health from the Redfish System resource
  (``Status.Health`` field). This reflects the overall rollup health status
  reported by the BMC, which typically aggregates the health of processors,
  memory, fans, power supplies, and storage.

Nodes using drivers without health monitoring support (e.g., IPMI) will have
their health field set to ``None``.

Client Usage
============

The health field is **not displayed by default** in ``baremetal node list``
output to maintain backward compatibility and keep the default output concise.

To view node health status, use one of the following methods:

**Query specific fields including health:**

.. code-block:: console

   $ baremetal node list --fields name health
   +-------------+----------+
   | Name        | Health   |
   +-------------+----------+
   | node-001    | OK       |
   | node-002    | Warning  |
   | node-003    | Critical |
   | node-004    | None     |
   +-------------+----------+

**Include health alongside other common fields:**

.. code-block:: console

   $ baremetal node list --fields name power_state provision_state maintenance health
   +-------------+-------------+--------------------+-------------+----------+
   | Name        | Power State | Provisioning State | Maintenance | Health   |
   +-------------+-------------+--------------------+-------------+----------+
   | node-001    | power on    | active             | False       | OK       |
   | node-002    | power on    | active             | False       | Warning  |
   | node-003    | power off   | manageable         | True        | Critical |
   +-------------+-------------+--------------------+-------------+----------+

**Use long listing format:**

.. code-block:: console

   $ baremetal node list --long

This includes health along with all other node fields.

**View health in node details:**

.. code-block:: console

   $ baremetal node show <node> --fields health
   +--------+----------+
   | Field  | Value    |
   +--------+----------+
   | health | OK       |
   +--------+----------+

API Version
===========

The ``health`` field is available starting from API microversion **1.109**.

Clients using older API versions will not see this field in responses.
