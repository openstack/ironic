.. -*- rst -*-

=============
Nodes (nodes)
=============




Show node details
=================

.. rest_method::  GET /v1/nodes/{node_id}

Shows details for a node.


Normal response codes: 200
Error response codes:413,405,404,403,401,400,503,


Request
-------

.. rest_parameters:: parameters.yaml

   - node_id: node_id
   - fields: fields




Response Example
----------------

.. literalinclude:: samples/node-show-response.json
   :language: javascript











Update node
===========

.. rest_method::  PATCH /v1/nodes/{node_id}

Updates a node.


Normal response codes: 200
Error response codes:413,415,405,404,403,401,400,503,409,


Request
-------

.. rest_parameters:: parameters.yaml

   - node_id: node_id




Response Example
----------------

.. literalinclude:: samples/node-show-response.json
   :language: javascript













Delete node
===========

.. rest_method::  DELETE /v1/nodes/{node_id}

Deletes a node.

Error response codes:204,413,415,405,404,403,401,400,503,409,


Request
-------

.. rest_parameters:: parameters.yaml

   - node_id: node_id















List nodes with details
=======================

.. rest_method::  GET /v1/nodes/detail

Lists all nodes with details.


Normal response codes: 200
Error response codes:413,405,404,403,401,400,503,


Request
-------





Response Example
----------------

.. literalinclude:: samples/nodes-list-details-response.json
   :language: javascript











Create node
===========

.. rest_method::  POST /v1/nodes

Creates a node.

Error response codes:201,413,415,405,404,403,401,400,503,409,


Request
-------
















List nodes
==========

.. rest_method::  GET /v1/nodes

Lists all nodes.


Normal response codes: 200
Error response codes:413,405,404,403,401,400,503,


Request
-------





Response Example
----------------

.. literalinclude:: samples/nodes-list-response.json
   :language: javascript










