.. -*- rst -*-

=====================================
Get Virtual Media (nodes)
=====================================

.. versionadded:: 1.93

Get a list of virtual media devices attached to a node using
the ``v1/nodes/{node_ident}/vmedia`` endpoint.

Get virtual media devices attached to a node
================================

.. rest_method:: GET /v1/nodes/{node_ident}/vmedia

Get virtual media devices attached to a node.

Normal response code: 200

Error codes: 400,401,403,404,409
