.. -*- rst -*-

=========================
Allocations (allocations)
=========================

The Allocation resource represents a request to find and allocate a Node for
deployment.

.. versionadded:: 1.52
    Allocation API was introduced.

Create Allocation
=================

.. rest_method::  POST /v1/allocations

Creates an allocation.

A Node can be requested by its resource class and traits. Additionally, Nodes
can be pre-filtered on the client side, and the resulting list of UUIDs and/or
names can be submitted as ``candidate_nodes``. Otherwise all nodes are
considered.

A Node is suitable for an Allocation if all of the following holds:

* ``provision_state`` is ``available``
* ``power_state`` is not ``null``
* ``maintenance`` is ``false``
* ``instance_uuid`` is ``null``
* ``resource_class`` matches requested one
* ``traits`` list contains all of the requested ones

The allocation process is asynchronous. The new Allocation is returned in
the ``allocating`` state, and the process continues in the background. If it
succeeds, the ``node_uuid`` field is populated with the Node's UUID, and the
Node's ``instance_uuid`` field is set to the Allocation's UUID.

If you want to backfill an allocation for an already deployed node, you can
pass the UUID or name of this node to ``node``. In this case the allocation
is created immediately, bypassing the normal allocation process. Other
parameters must be missing or match the provided node.

.. versionadded:: 1.52
    Allocation API was introduced.

.. versionadded:: 1.58
    Added support for backfilling allocations.

.. versionadded:: 1.60
  Introduced the ``owner`` field.

Normal response codes: 201

Error response codes: 400, 401, 403, 409, 503

Request
-------

.. rest_parameters:: parameters.yaml

   - resource_class: req_allocation_resource_class
   - candidate_nodes: req_candidate_nodes
   - name: req_allocation_name
   - traits: req_allocation_traits
   - uuid: req_uuid
   - extra: req_extra
   - node: req_allocation_node
   - owner: owner

Request Example
---------------

.. literalinclude:: samples/allocation-create-request.json
   :language: javascript

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
   - owner: owner
   - extra: extra
   - created_at: created_at
   - updated_at: updated_at
   - links: links

Response Example
----------------

.. literalinclude:: samples/allocation-create-response.json
   :language: javascript

List Allocations
================

.. rest_method::  GET /v1/allocations

Lists all Allocations.

.. versionadded:: 1.52
    Allocation API was introduced.

.. versionadded:: 1.60
  Introduced the ``owner`` field.

Normal response codes: 200

Error response codes: 400, 401, 403, 404

Request
-------

.. rest_parameters:: parameters.yaml

   - node: r_allocation_node
   - resource_class: r_resource_class
   - state: r_allocation_state
   - owner: owner
   - fields: fields
   - limit: limit
   - marker: marker
   - sort_dir: sort_dir
   - sort_key: sort_key

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
   - owner: owner
   - extra: extra
   - created_at: created_at
   - updated_at: updated_at
   - links: links

Response Example
----------------

.. literalinclude:: samples/allocations-list-response.json
   :language: javascript

Show Allocation Details
=======================

.. rest_method::  GET /v1/allocations/{allocation_id}

Shows details for an Allocation.

.. versionadded:: 1.52
    Allocation API was introduced.

.. versionadded:: 1.60
  Introduced the ``owner`` field.

Normal response codes: 200

Error response codes: 400, 401, 403, 404

Request
-------

.. rest_parameters:: parameters.yaml

   - fields: fields
   - allocation_id: allocation_ident

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
   - owner: owner
   - extra: extra
   - created_at: created_at
   - updated_at: updated_at
   - links: links

Response Example
----------------

.. literalinclude:: samples/allocation-show-response.json
   :language: javascript

Update Allocation
=================

.. rest_method::  PATCH /v1/allocations/{allocation_id}

Updates an allocation. Allows updating only name and extra fields.

.. versionadded:: 1.57
    Allocation update API was introduced.

Normal response codes: 200

Error response codes: 400, 401, 403, 404, 409, 503

Request
-------

The BODY of the PATCH request must be a JSON PATCH document, adhering to
`RFC 6902 <https://tools.ietf.org/html/rfc6902>`_.

.. rest_parameters:: parameters.yaml

   - allocation_id: allocation_ident
   - name: req_allocation_name
   - extra: req_extra

Request Example
---------------

.. literalinclude:: samples/allocation-update-request.json
   :language: javascript

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
   - owner: owner
   - extra: extra
   - created_at: created_at
   - updated_at: updated_at
   - links: links

Response Example
----------------

.. literalinclude:: samples/allocation-update-response.json
   :language: javascript

Delete Allocation
=================

.. rest_method::  DELETE /v1/allocations/{allocation_id}

Deletes an Allocation.

If the Allocation has a Node associated, the Node's ``instance_uuid`` is reset.

The deletion will fail if the Allocation has a Node assigned and the Node is
``active`` and not in the maintenance mode.

.. versionadded:: 1.52
    Allocation API was introduced.

Normal response codes: 204

Error response codes: 400, 401, 403, 404, 409, 503

Request
-------

.. rest_parameters:: parameters.yaml

  - allocation_id: allocation_ident
