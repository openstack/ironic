.. -*- rst -*-

===============
Volume (volume)
===============

.. versionadded:: 1.32

Information for connecting remote volumes to a node can be associated with a
Node. There are two types of resources, Volume connectors and Volume targets.
Volume connectors contain initiator information of Nodes. Volume targets
contain target information of remote volumes.

Listing, Searching, Creating, Updating, and Deleting of Volume connector
resources are done through the ``v1/volume/connectors`` resource. The same
operations for Volume targets are done through the ``v1/volume/targets``
resources.

List Links of Volume Resources
==============================

.. rest_method:: GET /v1/volume

Return a list of links to all volume resources.

Normal response code: 200

Request
-------

Response
--------

.. rest_parameters:: parameters.yaml

    - connectors: volume_connectors_link
    - targets: volume_targets_link
    - links: links

**Example Volume list response:**

.. literalinclude:: samples/volume-list-response.json
   :language: javascript


List Volume Connectors
======================

.. rest_method:: GET /v1/volume/connectors

Return a list of Volume connectors for all nodes.

By default, this query will return the UUID, node UUID, type, and connector ID
for each Volume connector.


Normal response code: 200

Error codes: 400,401,403,404

Request
-------

.. rest_parameters:: parameters.yaml

    - node: r_volume_connector_node_ident
    - fields: fields
    - detail: detail
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

**Example Volume connector list response:**

.. literalinclude:: samples/volume-connector-list-response.json
   :language: javascript

**Example detailed Volume connector list response:**

.. literalinclude:: samples/volume-connector-list-detail-response.json
   :language: javascript


Create Volume Connector
=======================

.. rest_method:: POST /v1/volume/connectors

Creates a new Volume connector resource.

This method requires a Node UUID, a connector type and a connector ID.

Normal response code: 201

Error codes: 400,401,403,404,409

Request
-------

.. rest_parameters:: parameters.yaml

    - node_uuid: req_node_uuid
    - type: volume_connector_type
    - connector_id: volume_connector_connector_id
    - extra: req_extra
    - uuid: req_uuid

**Example Volume connector creation request:**

.. literalinclude:: samples/volume-connector-create-request.json
   :language: javascript

Response
--------

.. rest_parameters:: parameters.yaml

    - uuid: uuid
    - type: volume_connector_type
    - connector_id: volume_connector_connector_id
    - node_uuid: node_uuid
    - extra: extra
    - links: links

**Example Volume connector creation response:**

.. literalinclude:: samples/volume-connector-create-response.json
   :language: javascript


Show Volume Connector Details
=============================

.. rest_method:: GET /v1/volume/connectors/{volume_connector_id}

Show details for the given Volume connector.

Normal response code: 200

Error codes: 400,401,403,404

Request
-------

.. rest_parameters:: parameters.yaml

    - volume_connector_id: volume_connector_id
    - fields: fields

Response
--------

.. rest_parameters:: parameters.yaml

    - uuid: uuid
    - type: volume_connector_type
    - connector_id: volume_connector_connector_id
    - node_uuid: node_uuid
    - extra: extra
    - links: links

**Example Volume connector details:**

.. literalinclude:: samples/volume-connector-create-response.json
   :language: javascript


Update a Volume Connector
=========================

.. rest_method:: PATCH /v1/volume/connectors/{volume_connector_id}

Update a Volume connector.

A Volume connector can be updated only while a node associated with the Volume
connector is powered off.

Normal response code: 200

Error codes: 400,401,403,404,409

Request
-------

The BODY of the PATCH request must be a JSON PATCH document, adhering to
`RFC 6902 <https://tools.ietf.org/html/rfc6902>`_.

.. rest_parameters:: parameters.yaml

    - volume_connector_id: volume_connector_id

**Example Volume connector update request:**

.. literalinclude:: samples/volume-connector-update-request.json
   :language: javascript

Response
--------

.. rest_parameters:: parameters.yaml

    - uuid: uuid
    - type: volume_connector_type
    - connector_id: volume_connector_connector_id
    - node_uuid: node_uuid
    - extra: extra
    - links: links

**Example Volume connector update response:**

.. literalinclude:: samples/volume-connector-update-response.json
   :language: javascript


Delete Volume Connector
=======================

.. rest_method:: DELETE /v1/volume/connector/{volume_connector_id}

Delete a Volume connector.

A Volume connector can be deleted only while a node associated with the Volume
connector is powered off.

Normal response code: 204

Error codes: 400,401,403,404,409

Request
-------

.. rest_parameters:: parameters.yaml

    - volume_connector_id: volume_connector_id

List Volume Targets
===================

.. rest_method:: GET /v1/volume/targets

Return a list of Volume targets for all nodes.

By default, this query will return the UUID, node UUID, volume type, boot
index, and volume ID for each Volume target.


Normal response code: 200

Error codes: 400,401,403,404

Request
-------

.. rest_parameters:: parameters.yaml

    - node: r_volume_target_node_ident
    - fields: fields
    - detail: detail
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

**Example Volume target list response:**

.. literalinclude:: samples/volume-target-list-response.json
   :language: javascript

**Example detailed Volume target list response:**

.. literalinclude:: samples/volume-target-list-detail-response.json
   :language: javascript


Create Volume Target
====================

.. rest_method:: POST /v1/volume/targets

Creates a new Volume target resource.

This method requires a Node UUID, volume type, volume ID, and boot index..

Normal response code: 201

Error codes: 400,401,403,404,409

Request
-------

.. rest_parameters:: parameters.yaml

    - node_uuid: req_node_uuid
    - volume_type: volume_target_volume_type
    - properties: req_volume_target_properties
    - boot_index: volume_target_boot_index
    - volume_id: volume_target_volume_id
    - extra: req_extra
    - uuid: req_uuid

**Example Volume target creation request:**

.. literalinclude:: samples/volume-target-create-request.json
   :language: javascript

Response
--------

.. rest_parameters:: parameters.yaml

    - uuid: uuid
    - volume_type: volume_target_volume_type
    - properties: volume_target_properties
    - boot_index: volume_target_boot_index
    - volume_id: volume_target_volume_id
    - extra: extra
    - node_uuid: node_uuid
    - links: links

**Example Volume target creation response:**

.. literalinclude:: samples/volume-target-create-response.json
   :language: javascript


Show Volume Target Details
==========================

.. rest_method:: GET /v1/volume/targets/{volume_target_id}

Show details for the given Volume target.

Normal response code: 200

Error codes: 400,401,403,404

Request
-------

.. rest_parameters:: parameters.yaml

    - volume_target_id: volume_target_id
    - fields: fields

Response
--------

.. rest_parameters:: parameters.yaml

    - uuid: uuid
    - volume_type: volume_target_volume_type
    - properties: volume_target_properties
    - boot_index: volume_target_boot_index
    - volume_id: volume_target_volume_id
    - extra: extra
    - node_uuid: node_uuid
    - links: links

**Example Volume target details:**

.. literalinclude:: samples/volume-target-create-response.json
   :language: javascript


Update a Volume Target
======================

.. rest_method:: PATCH /v1/volume/targets/{volume_target_id}

Update a Volume target.

A Volume target can be updated only while a node associated with the Volume
target is powered off.

Normal response code: 200

Error codes: 400,401,403,404,409

Request
-------

The BODY of the PATCH request must be a JSON PATCH document, adhering to
`RFC 6902 <https://tools.ietf.org/html/rfc6902>`_.

.. rest_parameters:: parameters.yaml

    - volume_target_id: volume_target_id

**Example Volume target update request:**

.. literalinclude:: samples/volume-target-update-request.json
   :language: javascript

Response
--------

.. rest_parameters:: parameters.yaml

    - uuid: uuid
    - volume_type: volume_target_volume_type
    - properties: volume_target_properties
    - boot_index: volume_target_boot_index
    - volume_id: volume_target_volume_id
    - extra: extra
    - node_uuid: node_uuid
    - links: links

**Example Volume target update response:**

.. literalinclude:: samples/volume-target-update-response.json
   :language: javascript


Delete Volume Target
====================

.. rest_method:: DELETE /v1/volume/target/{volume_target_id}

Delete a Volume target.

A Volume target can be deleted only while a node associated with the Volume
target is powered off.

Normal response code: 204

Error codes: 400,401,403,404,409

Request
-------

.. rest_parameters:: parameters.yaml

    - volume_target_id: volume_target_id
