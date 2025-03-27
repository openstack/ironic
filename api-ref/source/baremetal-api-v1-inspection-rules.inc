.. -*- rst -*-

===================================
Inspection rules (inspection_rules)
===================================

Inspection Rules consist of conditions that evaluate against inspection data
and actions that run on a node when conditions are met during inspection.

.. versionadded:: 1.96
    Inspection Rules API was introduced.

Create Inspection Rule
======================

.. rest_method::  POST /v1/inspection_rules

Creates an inspection rule.

.. versionadded:: 1.96
    Inspection Rules API was introduced.

Normal response codes: 201

Error response codes: 400, 401, 403, 409

Request
-------

.. rest_parameters:: parameters.yaml

   - uuid: req_uuid
   - description: inspection_rule_description
   - conditions: inspection_rule_conditions
   - actions: inspection_rule_actions
   - phase: inspection_rule_phase
   - priority: inspection_rule_priority
   - sensitive: inspection_rule_sensitive

Request Inspection Rule Condition
---------------------------------

.. rest_parameters:: parameters.yaml

   - op: inspection_rule_condition_op
   - args: inspection_rule_condition_args
   - loop: inspection_rule_condition_loop
   - multiple: inspection_rule_condition_multiple

Request Inspection Rule Action
------------------------------

.. rest_parameters:: parameters.yaml

   - op: inspection_rule_action_op
   - args: inspection_rule_action_args
   - loop: inspection_rule_action_loop

Request Example
---------------

.. literalinclude:: samples/inspection-rule-create-request.json
   :language: javascript

Response Parameters
-------------------

.. rest_parameters:: parameters.yaml

   - uuid: uuid
   - description: inspection_rule_description
   - conditions: inspection_rule_conditions
   - actions: inspection_rule_actions
   - phase: inspection_rule_phase
   - priority: inspection_rule_priority
   - sensitive: inspection_rule_sensitive
   - created_at: created_at
   - updated_at: updated_at
   - links: links

Response Example
----------------

.. literalinclude:: samples/inspection-rule-create-response.json
   :language: javascript

List Inspection Rules
=====================

.. rest_method::  GET /v1/inspection_rules

Lists all inspection rules.

.. versionadded:: 1.96
    Inspection Rules API was introduced.

Normal response codes: 200

Error response codes: 400, 401, 403, 404

Request
-------

.. rest_parameters:: parameters.yaml

   - detail: detail
   - phase: req_inspection_rule_phase

Response Parameters
-------------------

.. rest_parameters:: parameters.yaml

   - uuid: uuid
   - description: inspection_rule_description
   - phase: inspection_rule_phase
   - priority: inspection_rule_priority
   - sensitive: inspection_rule_sensitive
   - created_at: created_at
   - updated_at: updated_at
   - links: links
   - conditions: inspection_rule_conditions
   - actions: inspection_rule_actions

Response Example
----------------

**Example inspection rule list response:**

.. literalinclude:: samples/inspection-rule-list-response.json
   :language: javascript

**Example detailed inspection rule list response:**

.. literalinclude:: samples/inspection-rule-detail-response.json
   :language: javascript

Show Inspection Rule Details
============================

.. rest_method::  GET /v1/inspection_rules/{rule_id}

Shows details for an inspection rule.

.. versionadded:: 1.96
    Inspection Rules API was introduced.

Normal response codes: 200

Error response codes: 400, 401, 403, 404

Request
-------

.. rest_parameters:: parameters.yaml

   - rule_id: inspection_rule_ident

Response Parameters
-------------------

.. rest_parameters:: parameters.yaml

   - uuid: uuid
   - description: inspection_rule_description
   - conditions: inspection_rule_conditions
   - actions: inspection_rule_actions
   - phase: inspection_rule_phase
   - priority: inspection_rule_priority
   - sensitive: inspection_rule_sensitive
   - created_at: created_at
   - updated_at: updated_at
   - links: links

Response Example
----------------

.. literalinclude:: samples/inspection-rule-show-response.json
   :language: javascript

Update an Inspection Rule
=========================

.. rest_method:: PATCH /v1/inspection_rules/{rule_id}

Update an inspection rule.

.. versionadded:: 1.96
    Inspection Rules API was introduced.

Normal response code: 200

Error response codes: 400, 401, 403, 404, 409

Request
-------

The BODY of the PATCH request must be a JSON PATCH document, adhering to
`RFC 6902 <https://tools.ietf.org/html/rfc6902>`_.

.. rest_parameters:: parameters.yaml

    - rule_id: inspection_rule_ident

.. literalinclude:: samples/inspection-rule-update-request.json
   :language: javascript

Response
--------

.. rest_parameters:: parameters.yaml

   - uuid: uuid
   - description: inspection_rule_description
   - conditions: inspection_rule_conditions
   - actions: inspection_rule_actions
   - phase: inspection_rule_phase
   - priority: inspection_rule_priority
   - sensitive: inspection_rule_sensitive
   - created_at: created_at
   - updated_at: updated_at
   - links: links

.. literalinclude:: samples/inspection-rule-update-response.json
   :language: javascript

Delete Inspection Rule
======================

.. rest_method::  DELETE /v1/inspection_rules/{rule_id}

Deletes an inspection rule.

.. versionadded:: 1.96
    Inspection Rules API was introduced.

Normal response codes: 204

Error response codes: 400, 401, 403, 404

Request
-------

.. rest_parameters:: parameters.yaml

  - rule_id: inspection_rule_ident

Delete All Inspection Rules
===========================

.. rest_method::  DELETE /v1/inspection_rules

Deletes all non-built-in inspection rules.

.. versionadded:: 1.96
    Inspection Rules API was introduced.

Normal response codes: 204

Error response codes: 400, 401, 403
