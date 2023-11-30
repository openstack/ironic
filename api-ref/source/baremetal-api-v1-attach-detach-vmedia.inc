.. -*- rst -*-

=====================================
Attach / Detach Virtual Media (nodes)
=====================================

.. versionadded:: 1.89

Attach a generic image as virtual media device to a node or remove
it from a node using the ``v1/nodes/{node_ident}/vmedia`` endpoint.

Attach a virtual media to a node
================================

.. rest_method:: POST /v1/nodes/{node_ident}/vmedia

Attach virtual media device to a node.

Normal response code: 204

Error codes: 400,401,403,404,409

Request
-------

.. rest_parameters:: parameters.yaml

    - node_ident: node_ident
    - device_type: vmedia_device_type
    - image_url: vmedia_image_url
    - image_download_source: vmedia_image_download_source

**Example request to attach virtual media to a Node:**

.. literalinclude:: samples/node-vmedia-attach-request.json


Detach virtual media from a node
================================

.. rest_method:: DELETE /v1/nodes/{node_ident}/vmedia

Detach virtual media device from a Node.

Normal response code: 204

Error codes: 400,401,403,404

Request
-------

.. rest_parameters:: parameters.yaml

    - node_ident: node_ident
