.. -*- rst -*-

====================================
Node Allocation (allocations, nodes)
====================================

Given a Node identifier (``uuid`` or ``name``), the API allows to get and
delete the associated allocation.

.. versionadded:: 1.52
    Allocation API was introduced.

Show Allocation by Node
=======================

.. rest_method::  GET /v1/nodes/{node_ident}/allocation

Shows details for an allocation.

.. versionadded:: 1.52
    Allocation API was introduced.

Normal response codes: 200

Error response codes: 400, 401, 403, 404

Request
-------

.. rest_parameters:: parameters.yaml

   - node_ident: node_ident
   - fields: fields

Response Parameters
-------------------

.. rest_parameters:: parameters.yaml

   - uuid: uuid
   - candidate_nodes: candidate_nodes
   - last_error: allocation_last_error
   - name: allocation_name
   - node_uuid: allocation_node
   - resource_class: allocation_resource_class
   - state: allocation_state
   - traits: allocation_traits
   - extra: extra
   - created_at: created_at
   - updated_at: updated_at
   - links: links

Response Example
----------------

.. literalinclude:: samples/allocation-show-response.json
   :language: javascript

Delete Allocation by Node
=========================

.. rest_method::  DELETE /v1/nodes/{node_ident}/allocation

Deletes the allocation of this node and resets its ``instance_uuid``.

The deletion will fail if the allocation the node is ``active`` and not in
the ``maintenance`` mode.

.. versionadded:: 1.52
    Allocation API was introduced.

Normal response codes: 204

Error response codes: 400, 401, 403, 404, 409, 503

Request
-------

.. rest_parameters:: parameters.yaml

  - node_ident: node_ident
