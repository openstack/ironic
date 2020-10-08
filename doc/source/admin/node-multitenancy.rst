==================
Node Multi-Tenancy
==================

This guide explains the steps needed to enable node multi-tenancy. This
feature enables non-admins to perform API actions on nodes, limited by
policy configuration. The Bare Metal service supports two kinds of
non-admin users:

* Owner: owns specific nodes and performs administrative actions on them
* Lessee: receives temporary and limited access to a node

Setting the Owner and Lessee
============================

Non-administrative access to a node is controlled through a node's ``owner``
or ``lessee`` attribute::

  baremetal node set --owner 080925ee2f464a2c9dce91ee6ea354e2  node-7
  baremetal node set --lessee 2a210e5ff114c8f2b6e994218f51a904  node-10


Configuring the Bare Metal Service Policy
=========================================

By default, the Bare Metal service  policy is configured so that a node
owner or lessee has no access to any node APIs. However, the policy
:doc:`policy file </configuration/sample-policy>` contains rules that
can be used to enable node API access::

  # Owner of node
  #"is_node_owner": "project_id:%(node.owner)s"

  # Lessee of node
  #"is_node_lessee": "project_id:%(node.lessee)s"

An administrator can then modify the policy file to expose individual node
APIs as follows::

  # Change Node provision status
  # PUT  /nodes/{node_ident}/states/provision
  #"baremetal:node:set_provision_state": "rule:is_admin"
  "baremetal:node:set_provision_state": "rule:is_admin or rule:is_node_owner or rule:is_node_lessee"

  # Update Node records
  # PATCH  /nodes/{node_ident}
  #"baremetal:node:update": "rule:is_admin or rule:is_node_owner"

In addition, it is safe to expose the ``baremetal:node:list`` rule, as the
node list function now filters non-admins by owner and lessee::

  # Retrieve multiple Node records, filtered by owner
  # GET  /nodes
  # GET  /nodes/detail
  #"baremetal:node:list": "rule:baremetal:node:get"
  "baremetal:node:list": ""

Note that ``baremetal:node:list_all`` permits users to see all nodes
regardless of owner/lessee, so it should remain restricted to admins.

Ports
-----

Port APIs can be similarly exposed to node owners and lessees::

  # Retrieve Port records
  # GET  /ports/{port_id}
  # GET  /nodes/{node_ident}/ports
  # GET  /nodes/{node_ident}/ports/detail
  # GET  /portgroups/{portgroup_ident}/ports
  # GET  /portgroups/{portgroup_ident}/ports/detail
  #"baremetal:port:get": "rule:is_admin or rule:is_observer"
  "baremetal:port:get": "rule:is_admin or rule:is_observer or rule:is_node_owner or rule:is_node_lessee"

  # Retrieve multiple Port records, filtered by owner
  # GET  /ports
  # GET  /ports/detail
  #"baremetal:port:list": "rule:baremetal:port:get"
  "baremetal:port:list": ""


Allocations
-----------

Allocations respect node tenancy as well. A restricted allocation creates
an allocation tied to a project, and that can only match nodes where that
project is the owner or lessee. Here is a sample set of allocation policy
rules that allow non-admins to use allocations effectively::

  # Retrieve Allocation records
  # GET  /allocations/{allocation_id}
  # GET  /nodes/{node_ident}/allocation
  #"baremetal:allocation:get": "rule:is_admin or rule:is_observer"
  "baremetal:allocation:get": "rule:is_admin or rule:is_observer or rule:is_allocation_owner"

  # Retrieve multiple Allocation records, filtered by owner
  # GET  /allocations
  #"baremetal:allocation:list": "rule:baremetal:allocation:get"
  "baremetal:allocation:list": ""

  # Retrieve multiple Allocation records
  # GET  /allocations
  #"baremetal:allocation:list_all": "rule:baremetal:allocation:get"

  # Create Allocation records
  # POST  /allocations
  #"baremetal:allocation:create": "rule:is_admin"

  # Create Allocation records that are restricted to an owner
  # POST  /allocations
  #"baremetal:allocation:create_restricted": "rule:baremetal:allocation:create"
  "baremetal:allocation:create_restricted": ""

  # Delete Allocation records
  # DELETE  /allocations/{allocation_id}
  # DELETE  /nodes/{node_ident}/allocation
  #"baremetal:allocation:delete": "rule:is_admin"
  "baremetal:allocation:delete": "rule:is_admin or rule:is_allocation_owner"

  # Change name and extra fields of an allocation
  # PATCH  /allocations/{allocation_id}
  #"baremetal:allocation:update": "rule:is_admin"
  "baremetal:allocation:update": "rule:is_admin or rule:is_allocation_owner"

Deployment and Metalsmith
-------------------------

Provisioning a node requires a specific set of APIs to be made available.
The following policy specifications are enough to allow a node owner to
use :metalsmith-doc:`Metalsmith <index.html>` to deploy upon a node::

  "baremetal:node:get": "rule:is_admin or rule:is_observer or rule:is_node_owner"
  "baremetal:node:list": ""
  "baremetal:node:update_extra": "rule:is_admin or rule:is_node_owner"
  "baremetal:node:update_instance_info": "rule:is_admin or rule:is_node_owner"
  "baremetal:node:validate": "rule:is_admin or rule:is_node_owner"
  "baremetal:node:set_provision_state": "rule:is_admin or rule:is_node_owner"
  "baremetal:node:vif:list": "rule:is_admin or rule:is_node_owner"
  "baremetal:node:vif:attach": "rule:is_admin or rule:is_node_owner"
  "baremetal:node:vif:detach": "rule:is_admin or rule:is_node_owner"
  "baremetal:allocation:get": "rule:is_admin or rule:is_observer or rule:is_allocation_owner"
  "baremetal:allocation:list": ""
  "baremetal:allocation:create_restricted": ""
  "baremetal:allocation:delete": "rule:is_admin or rule:is_allocation_owner"
  "baremetal:allocation:update": "rule:is_admin or rule:is_allocation_owner"
