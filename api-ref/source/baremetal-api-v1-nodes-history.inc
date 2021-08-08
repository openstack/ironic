.. -*- rst -*-

================
History of nodes
================

.. versionadded:: 1.78

Identifying history of events from nodes is available via API version 1.78 via
the ``v1/nodes/{node_ident}/history`` endpoint. In default policy
configuration, only "System" scoped users as well as owners who are listed
owners of associated nodes can list and retrieve nodes.

List history entries for a node
===============================

.. rest_method:: GET /v1/nodes/{node_ident}/history

Normal response code: 200

Error codes: 400,401,403,404

Request
-------

.. rest_parameters:: parameters.yaml

   - node_ident: node_ident
   - detail: detail
   - marker: marker
   - limit: limit

Response
--------

.. rest_parameters:: parameters.yaml

   - history: n_history

**Example list of history events from a node:**

.. literalinclude:: samples/node-history-list-response.json
   :language: javascript

Retrieve a specific history entry
=================================

.. rest_method:: GET /v1/nodes/{node_ident}/history/{history_event_uuid}

Request
-------

.. rest_parameters:: parameters.yaml

   - node_ident: node_ident
   - history_event_uuid: history_event_ident

Response
--------

.. rest_parameters:: parameters.yaml

   - uuid: uuid
   - created_at: created_at
   - user: history_user_ident
   - severity: history_severity
   - event: history_event
   - event_type: history_event_type
   - conductor: hostname

Deleting history entries for a node
===================================

Due to the nature of an immutable history record, records cannot be deleted
via the REST API. Records and ultimately expired history records are managed
by the conductor.
