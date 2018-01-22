.. -*- rst -*-

===================
Node Traits (nodes)
===================

.. versionadded:: 1.37

Node traits are used for scheduling in the Compute service, using qualitative
attributes to influence the placement of instances to bare metal compute nodes.
Traits specified for a node in the Bare Metal service will be registered on the
corresponding resource provider in the Compute service's placement API.

Traits can be either standard or custom.  Standard traits are listed in the
`os_traits library <https://docs.openstack.org/os-traits/latest/>`_.  Custom
traits must meet the following requirements:

* prefixed with ``CUSTOM_``
* contain only upper case characters A to Z, digits 0 to 9, or underscores
* no longer than 255 characters in length

A bare metal node can have a maximum of 50 traits.

List Traits of a Node
=====================

.. rest_method:: GET /v1/nodes/{node_ident}/traits

Return a list of traits for the node.

Normal response code: 200

Error codes: 400,401,403,404

Request
-------

.. rest_parameters:: parameters.yaml

    - node_ident: node_ident

Response
--------

.. rest_parameters:: parameters.yaml

    - traits: n_traits

**Example list of traits for the node:**

.. literalinclude:: samples/node-traits-list-response.json
   :language: javascript


Set all traits of a node
========================

.. rest_method:: PUT /v1/nodes/{node_ident}/traits

Set all traits of a node, replacing any existing traits.

Normal response code: 204

Error codes: 400,401,403,404,409

Request
-------

.. rest_parameters:: parameters.yaml

    - node_ident: node_ident
    - traits: n_traits

**Example request to set all traits of a Node:**

.. literalinclude:: samples/node-set-traits-request.json


Add a trait to a node
=====================

.. rest_method:: PUT /v1/nodes/{node_ident}/traits/{trait}

Add a single trait to a node.

Normal response code: 204

Error codes: 400,401,403,404,409

Request
-------

.. rest_parameters:: parameters.yaml

    - node_ident: node_ident
    - trait: trait


Remove all traits from a node
=============================

.. rest_method:: DELETE /v1/nodes/{node_ident}/traits

Normal response code: 204

Error codes: 400,401,403,404,409

Request
-------

.. rest_parameters:: parameters.yaml

    - node_ident: node_ident


Remove a trait from a node
==========================

Remove a single trait from a node.

.. rest_method:: DELETE /v1/nodes/{node_ident}/traits/{trait}

Normal response code: 204

Error codes: 400,401,403,404,409

Request
-------

.. rest_parameters:: parameters.yaml

    - node_ident: node_ident
    - trait: trait
