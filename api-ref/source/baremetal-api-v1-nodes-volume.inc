.. -*- rst -*-

================================================
Listing Volume resources by Node (nodes, volume)
================================================

.. versionadded:: 1.32

Given a Node identifier (``uuid`` or ``name``), the API exposes the list of,
and details of, all Volume resources associated with that Node.

These endpoints do not allow modification of the Volume connectors and Volume
targets; that should be done by accessing the Volume resources under the
``/v1/volume/connectors`` and ``/v1/volume/targets`` endpoint.

List Links of Volume Resources by Node
======================================

.. rest_method:: GET /v1/nodes/{node_ident}/volume

Return a list of links to all volume resources associated with ``node_ident``.

Normal response code: 200

Request
-------

.. rest_parameters:: parameters.yaml

    - node_ident: node_ident

Response
--------

.. rest_parameters:: parameters.yaml

    - connectors: volume_connectors_link
    - targets: volume_targets_link
    - links: links

**Example Volume list response:**

.. literalinclude:: samples/node-volume-list-response.json
   :language: javascript


List Volume connectors by Node
==============================

.. rest_method:: GET /v1/nodes/{node_ident}/volume/connectors

Return a list of bare metal Volume connectors associated with ``node_ident``.

Normal response code: 200

Error codes: 400,401,403,404

Request
-------

.. rest_parameters:: parameters.yaml

    - node_ident: node_ident
    - fields: fields
    - limit: limit
    - marker: marker
    - sort_dir: sort_dir
    - sort_key: sort_key

Response
--------

.. rest_parameters:: parameters.yaml

    - connectors: volume_connectors
    - uuid: uuid
    - type: volume_connector_type
    - connector_id: volume_connector_connector_id
    - node_uuid: node_uuid
    - extra: extra
    - links: links
    - next: next

**Example list of Node's Volume connectors:**

.. literalinclude:: samples/node-volume-connector-list-response.json

**Example detailed list of Node's Volume connectors:**

.. literalinclude:: samples/node-volume-connector-detail-response.json


List Volume targets by Node
===========================

.. rest_method:: GET /v1/nodes/{node_ident}/volume/targets

Return a list of bare metal Volume targets associated with ``node_ident``.

Normal response code: 200

Error codes: 400,401,403,404

Request
-------

.. rest_parameters:: parameters.yaml

    - node_ident: node_ident
    - fields: fields
    - limit: limit
    - marker: marker
    - sort_dir: sort_dir
    - sort_key: sort_key

Response
--------

.. rest_parameters:: parameters.yaml

    - targets: volume_targets
    - uuid: uuid
    - volume_type: volume_target_volume_type
    - properties: volume_target_properties
    - boot_index: volume_target_boot_index
    - volume_id: volume_target_volume_id
    - extra: extra
    - node_uuid: node_uuid
    - links: links
    - next: next

**Example list of Node's Volume targets:**

.. literalinclude:: samples/node-volume-target-list-response.json

**Example detailed list of Node's Volume targets:**

.. literalinclude:: samples/node-volume-target-detail-response.json
