.. -*- rst -*-

==================================
VIFs (Virtual Interfaces) of nodes
==================================

Starting with API version 1.28 attaching and detaching VIFs (Virtual Interfaces)
to or from a node are done via the ``v1/nodes/{node_ident}/vifs`` endpoint. Attaching
a VIF to a node means that a VIF will be mapped to a free port or port group of
the specified node.

List attached VIFs of a Node
============================

.. rest_method:: GET /v1/nodes/{node_ident}/vifs

Return a list of VIFs that are attached to the node.

Normal response code: 200

Error codes: 400,401,403,404

Response
--------

.. rest_parameters:: parameters.yaml

    - id: node_vif_ident
    - vifs: n_vifs
    - node_ident: node_ident

**Example list of VIFs that are attached to the node:**

.. literalinclude:: samples/node-vif-list-response.json
   :language: javascript


Attach a VIF to a node
======================

.. rest_method:: POST /v1/nodes/{node_ident}/vifs

Attach a VIF to a node.

Normal response code: 204

Error codes: 400,401,403,404,409

Request
-------

.. rest_parameters:: parameters.yaml

    - id: node_vif_ident
    - node_ident: node_ident

**Example request to attach a VIF to a Node:**

.. literalinclude:: samples/node-vif-attach-request.json


Detach VIF from a node
======================

.. rest_parameters:: parameters.yaml

    - node_ident: node_ident
    - node_vif_ident: node_vif_ident

.. rest_method:: DELETE /v1/nodes/{node_ident}/vifs/{node_vif_ident}

Detach VIF from a Node.

Normal response code: 204

Error codes: 400,401,403,404
