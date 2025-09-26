.. meta::
   :description: Implement availability zones with Ironic using conductor groups and shards. Multi-datacenter deployments, fault tolerance, and resource partitioning strategies.
   :keywords: availability zones, conductor groups, shards, fault tolerance, multi-datacenter, resource partitioning, high availability, geographic distribution
   :author: OpenStack Ironic Team
   :robots: index, follow
   :audience: cloud architects, system administrators

==========================================
Availability Zones and Resource Isolation
==========================================

Overview
========

While Ironic does not implement traditional OpenStack Availability Zones like
Nova and Neutron, it provides a **three-tier approach** for resource
partitioning and isolation that achieves comprehensive availability
zone functionality:

* **Multiple Ironic Deployments**: Completely separate Ironic services
                                   targeted by different Nova compute nodes
* **Conductor Groups**: Physical/geographical resource partitioning within
                        a deployment
* **Shards**: Logical grouping for operational scaling within a deployment

This document explains how these mechanisms work together and how to achieve
sophisticated availability zone functionality across your infrastructure.
This document does **not** cover similar effect which can be achieved
through the use of API level Role Based Access Control through the
``owner`` and ``lessee`` fields.

.. contents:: Table of Contents
   :local:
   :depth: 2

Comparison with Other OpenStack Services
========================================

+------------------+-------------------+------------------------+
| Service          | Mechanism         | Purpose                |
+==================+===================+========================+
| Nova             | Availability      | Instance placement     |
|                  | Zones (host       | across fault domains   |
|                  | aggregates)       |                        |
+------------------+-------------------+------------------------+
| Neutron          | Agent AZs         | Network service HA     |
+------------------+-------------------+------------------------+
| **Ironic**       | **Multiple        | **Complete service     |
|                  | Deployments +     | isolation + physical   |
|                  | Conductor Groups  | partitioning +         |
|                  | + Shards**        | operational scaling**  |
+------------------+-------------------+------------------------+

Ironic's Three-Tier Approach
=============================

Tier 1: Multiple Ironic Deployments
------------------------------------

The highest level of isolation involves running **completely separate
Ironic services** that Nova and other API users can target independently.

**Use Cases**:

* Complete geographic separation (different regions/countries)
* Regulatory compliance requiring full data isolation
* Independent upgrade cycles and operational teams

**Implementation**: Configure separate Nova compute services to target
different Ironic deployments using Nova's Ironic driver configuration.

**Benefits**:

* Complete fault isolation - failure of one deployment doesn't affect others
* Independent scaling, upgrades, and maintenance
* Different operational policies per deployment
* Complete API endpoint separation

Tier 2: Conductor Groups (Physical Partitioning)
-------------------------------------------------

Within a single Ironic deployment, conductor groups provides
**physical resource partitioning**.

**Use Cases**:

* Separate nodes by datacenter/availability zone within a region
* Separate nodes by conductor groups for conductor resource management
* Isolate hardware types or vendors
* Create fault domains for high availability
* Manage nodes with different network connectivity

Conductor groups control **which conductor manages which nodes**.
Each conductor can be assigned to a specific group, and will only
manage nodes that belong to the same group.

A classical challenge of Ironic is that it is able to manage far more
Bare Metal nodes than a single ``nova-compute`` service is designed to
support. The primary answer for this issue is to leverage Shards first,
and then continue to evolve based upon operational needs.

See: :doc:`conductor-groups` for detailed configuration.

.. _availability-zones-shards:

Tier 3: Shards (Logical Partitioning)
--------------------------------------

The finest level of granularity for **operational and client-side grouping**.

**Use Cases**:

* Horizontal scaling of operations
* Parallelize maintenance tasks
* Create logical groupings for different teams

Shards can be used by clients, including Nova, to limit the scope of their
requests to a logical and declared subset of nodes which prevents multiple
``nova-compute`` services from being able to see and work with the same
node on multiple ``nova-compute`` services.

.. note::
   Shards are client-side constructs - Ironic itself does not use shard
   values internally.

.. versionadded:: 1.82
   Shard support was added in API version 1.82.

.. warning::
   Once set, a shard should not be changed. Nova's model of leveraging the
   Ironic API does not permit this value to be changed after the fact.

Common Deployment Patterns
===========================

Pattern 1: Multi-Region with Complete Isolation
------------------------------------------------

**Use Case**: Global deployment with regulatory compliance

**Implementation**:

- **Multiple Deployments**: ``ironic-us-east``, ``ironic-eu-west``, ``ironic-apac``
- **Nova Configuration**: Separate compute services per region
- **Conductor Groups**: Optional within each deployment
- **Shards**: Operational grouping within regions

**Example Nova Configuration**:

.. code-block:: ini

   # nova-compute for US East region
   [ironic]
   auth_url = https://keystone-us-east.example.com/v3
   endpoint_override = https://ironic-us-east.example.com

   # nova-compute for EU West region
   [ironic]
   auth_url = https://keystone-eu-west.example.com/v3
   endpoint_override = https://ironic-eu-west.example.com

.. note::
   The above indicated ``endpoint_override`` configuration is provided
   for illustrative purposes to stress endpoints would be distinctly
   different.

Pattern 2: Single Region with Datacenter Separation
----------------------------------------------------

**Use Case**: Metro deployment across multiple datacenters

**Implementation**:

- **Single Deployment**: One Ironic service
- **Conductor Groups**: ``datacenter-1``, ``datacenter-2``, ``datacenter-3``
- **Nova Configuration**: Target specific conductor groups
- **Shards**: Optional operational grouping

In this case, we don't expect BMC management network access to occur between
datacenters. Thus each datacenter is configured with it's own group of
conductors.

**Example Configuration**:

.. code-block:: bash

   # Configure Nova compute to target specific conductor group
   [ironic]
   conductor_group = datacenter-1

   # Configure conductors (ironic.conf)
   [conductor]
   conductor_group = datacenter-1

   # Assign nodes
   baremetal node set --conductor-group datacenter-1 <node-uuid>

.. note::
   Some larger operators who leverage conductor groups have suggested
   that it is sometimes logical to have a conductor set without a
   ``conductor_group`` set. This helps prevent orphaning nodes because
   Ironic routes all changes to the conductor which presently manages
   the node.

Pattern 3: Operational Scaling Within Datacenters
--------------------------------------------------

**Use Case**: Large deployment requiring parallel operations

**Implementation**:

- **Single Deployment**: One Ironic service
- **Conductor Groups**: By datacenter or hardware type
- **Shards**: Operational batches for maintenance/upgrades
- **Nova Configuration**: May target specific conductor groups

**Example**:

.. code-block:: bash

   # Set up conductor groups by hardware
   baremetal node set --conductor-group dell-servers <node-uuid-1>
   baremetal node set --conductor-group hpe-servers <node-uuid-2>

   # Create operational shards for maintenance
   baremetal node set --shard maintenance-batch-1 <node-uuid-1>
   baremetal node set --shard maintenance-batch-2 <node-uuid-2>

Pattern 4: Hybrid Multi-Tier Approach
--------------------------------------

**Use Case**: Complex enterprise deployment

**Implementation**: All three tiers working together

**Example Architecture**:

.. code-block:: bash

   # Deployment 1: Production East Coast
   # Nova compute service targets ironic-prod-east
   [ironic]
   endpoint_override = https://ironic-prod-east.example.com
   conductor_group = datacenter-east

   # Within this deployment:
   baremetal node set --conductor-group datacenter-east --shard prod-batch-a <node-uuid>

   # Deployment 2: Production West Coast
   # Nova compute service targets ironic-prod-west
   [ironic]
   endpoint_override = https://ironic-prod-west.example.com
   conductor_group = datacenter-west

Nova Integration and Configuration
==================================

Targeting Multiple Ironic Deployments
--------------------------------------

Nova's Ironic driver can be configured to target different Ironic services:

**Per-Compute Service Configuration**:

.. code-block:: ini

   # /etc/nova/nova.conf on compute-service-1
   [ironic]
   auth_url = https://keystone-region1.example.com/v3
   endpoint_override = https://ironic-region1.example.com
   conductor_group = region1-zone1

   # /etc/nova/nova.conf on compute-service-2
   [ironic]
   auth_url = https://keystone-region2.example.com/v3
   endpoint_override = https://ironic-region2.example.com
   conductor_group = region2-zone1

**Advanced Options**:

.. code-block:: ini

   [ironic]
   # Target specific conductor group within deployment
   conductor_group = datacenter-east

   # Target specific shard within deployment
   shard = production-nodes

   # Connection retry configuration
   api_max_retries = 60
   api_retry_interval = 2

.. seealso::
   `Nova Ironic Hypervisor Configuration <https://github.com/openstack/nova/blob/master/doc/source/admin/configuration/hypervisor-ironic.rst>`_
   for complete Nova configuration details.

Scaling Considerations
----------------------

**Nova Compute Service Scaling**:

* Single nova-compute can handle several hundred Ironic nodes efficiently.
* Consider multiple compute services for >1000 nodes per deployment.
  Nova-compute is modeled on keeping a relatively small number of "instances"
  per nova-compute process. For example, 250 baremetal nodes.
* One nova-compute process per conductor group or shard is expected.
* A ``conductor_group`` which is independent of a nova-compute service
  configuration can be changed at any time. A shard should never be
  changed once it has been introduced to a nova-compute process.

**Multi-Deployment Benefits**:

* Independent scaling per deployment
* Isolated failure domains
* Different operational schedules

Integration Considerations
==========================

Network Considerations
----------------------

Ironic's partitioning works alongside physical network configuration:

* Physical networks can span multiple conductor groups
* Consider network topology when designing conductor group boundaries
* Ensure network connectivity between conductors and their assigned nodes

.. seealso::
   :doc:`networking` for detailed network configuration guidance

Nova Placement and Scheduling
------------------------------

When using Ironic with Nova:

* Nova's availability zones operate independently of Ironic's partitioning
* Use resource classes and traits for capability-based scheduling

.. seealso::
   :doc:`../install/configure-nova-flavors` for flavor and scheduling configuration

API Client Usage
================

Working Across Multiple Deployments
------------------------------------

When managing multiple Ironic deployments, use separate client configurations:

.. code-block:: bash

   # Configure client for deployment 1
   export OS_AUTH_URL=https://keystone-east.example.com/v3
   export OS_ENDPOINT_OVERRIDE=https://ironic-east.example.com
   baremetal node list

   # Configure client for deployment 2
   export OS_AUTH_URL=https://keystone-west.example.com/v3
   export OS_ENDPOINT_OVERRIDE=https://ironic-west.example.com
   baremetal node list

Filtering by Conductor Group
-----------------------------

.. code-block:: bash

   # List nodes by conductor group
   baremetal node list --conductor-group datacenter-east

   # List ports by node conductor group
   baremetal port list --conductor-group datacenter-east

Filtering by Shard
-------------------

.. code-block:: bash

   # List nodes by shard
   baremetal node list --shard batch-a

   # Get shard distribution
   baremetal shard list

   # Find nodes without a shard assignment
   baremetal node list --unsharded

Combined Filtering Within Deployments
--------------------------------------

.. code-block:: bash

   # Within a single deployment, filter by conductor group and shard
   baremetal node list --conductor-group datacenter-1 --shard maintenance-batch-a

   # Set both conductor group and shard on a node
   baremetal node set --conductor-group datacenter-east --shard batch-a <node-uuid>

   # Get overview of resource distribution
   baremetal shard list
   baremetal conductor list

Best Practices
==============

Deployment Strategy Planning
----------------------------

1. **Assess isolation requirements**: Determine if you need complete service separation
2. **Plan geographic distribution**: Use multiple deployments for true regional separation
3. **Design conductor groups**: Align with physical/network boundaries
4. **Implement shard strategy**: Plan for operational efficiency
5. **Configure Nova appropriately**: Match Nova compute services to your architecture

Operational Considerations
--------------------------

**Multiple Deployments**:

* Maintain consistent tooling across deployments
* Plan for cross-deployment migrations if needed
* Monitor each deployment independently
* Coordinate upgrade schedules

**Within Deployments**:

* Monitor conductor distribution: ``baremetal shard list``
* Ensure conductor redundancy per group
* Align network topology with conductor groups
* Automate shard management for balance

**Nova Integration**:

* Plan compute service distribution across deployments
* Monitor nova-compute to Ironic node ratios
* Test failover scenarios between compute services

Naming Conventions
------------------

Naming patterns can be defined by the infrastructure operator and below
are some basic suggestions which may be relevant based upon operational
requirements.

**Conductor Groups**:

* Geographic: ``datacenter-east``, ``region-us-west``, ``rack-01``
* Hardware: ``dell-servers``, ``hpe-gen10``, ``gpu-nodes``
* Network: ``vlan-100``, ``isolated-network``

**Shards**:

* Operational: ``maintenance-batch-1``, ``upgrade-group-a``
* Size-based: ``small-nodes``, ``large-memory``
* Temporal: ``weekend-maintenance``, ``business-hours``

Decision Matrix
---------------

Choose your approach based on requirements:

+-------------------------+-------------------+-----------------+---------------+
| **Requirement**         | **Multiple        | **Conductor     | **Shards**    |
|                         | Deployments**     | **Groups**      |               |
+=========================+===================+=================+===============+
| Complete isolation      | ✓ Best            | ✓ Good          | ✗ No          |
+-------------------------+-------------------+-----------------+---------------+
| Independent upgrades    | ✓ Complete        | ✓ Partial       | ✗ No          |
+-------------------------+-------------------+-----------------+---------------+
| Geographic separation   | ✓ Best            | ✓ Good          | ✗ No          |
+-------------------------+-------------------+-----------------+---------------+
| Operational scaling     | ✗ Overhead        | ✓ Good          | ✓ Best        |
+-------------------------+-------------------+-----------------+---------------+
| Resource efficiency     | ✗ Lower           | ✓ Good          | ✓ Best        |
+-------------------------+-------------------+-----------------+---------------+

Troubleshooting
===============

Multiple Deployment Issues
---------------------------

**Connectivity Problems**:

.. code-block:: bash

   # Test connectivity to each deployment
   baremetal --os-endpoint-override https://ironic-east.example.com node list
   baremetal --os-endpoint-override https://ironic-west.example.com node list

**Nova Configuration Issues**:

.. code-block:: bash

   # Check Nova compute service registration
   openstack compute service list --service nova-compute

   # Verify Nova can reach Ironic
   grep -i ironic /var/log/nova/nova-compute.log

**Cross-Deployment Node Migration**:

.. code-block:: bash

   # Export node data from source deployment
   baremetal node show --fields all <node-uuid>

   # Import to destination deployment (manual process)
   # Note: Requires careful planning and may need custom tooling

Common Issues Within Deployments
---------------------------------

**Orphaned nodes**: Nodes without matching conductor groups cannot be managed

.. code-block:: bash

   # Find nodes without conductor groups
   baremetal node list --conductor-group ""

   # List available conductor groups
   baremetal conductor list

**Unbalanced shards**: Monitor node distribution across shards

.. code-block:: bash

   # Check shard distribution
   baremetal shard list

   # Find heavily loaded shards
   baremetal node list --shard <shard-name> | wc -l

**Missing conductor groups**: Ensure all groups have active conductors

.. code-block:: bash

   # Check conductor status
   baremetal conductor list

   # Verify conductor group configuration
   # Check ironic.conf [conductor] conductor_group setting

Migration Scenarios
-------------------

**Moving nodes between conductor groups**:

.. code-block:: bash

   # Move node to different conductor group
   baremetal node set --conductor-group new-group <node-uuid>

**Reassigning shards**:

.. code-block:: bash

   # Change node shard assignment
   baremetal node set --shard new-shard <node-uuid>

   # Remove shard assignment
   baremetal node unset --shard <node-uuid>

.. warning::
   Shards should never be changed once a nova-compute service has
   identified a node in Ironic. Changing a shard at this point is
   an unsupported action. As such, Ironic's API RBAC policy restricts
   these actions to a "System-Scoped Admin" user. Normal Admin users
   are denied this capability due the restriction and requirement
   on the nova-compute side of the consumption of shards.

See Also
========

* :doc:`conductor-groups` - Detailed conductor group configuration
* :doc:`networking` - Physical network considerations
* :doc:`../install/refarch/index` - Reference architectures
* :doc:`multitenancy` - Multi-tenant deployments
* :doc:`tuning` - Performance tuning considerations
* `Nova Ironic Driver Documentation <https://github.com/openstack/nova/blob/master/doc/source/admin/configuration/hypervisor-ironic.rst>`_
* `Nova Ironic Configuration Options <https://github.com/openstack/nova/blob/master/nova/conf/ironic.py>`_

