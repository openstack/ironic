.. -*- rst -*-

===================
Runbooks (runbooks)
===================

The Runbook resource represents a collection of steps that define a
series of actions to be executed on a node. Runbooks enable users to perform
complex operations in a predefined, automated manner. A runbook is
matched for a node if the runbook's name matches a trait in the node.

.. versionadded:: 1.92
    Runbook API was introduced.

Create Runbook
==============

.. rest_method::  POST /v1/runbooks

Creates a runbook.

.. versionadded:: 1.92
    Runbook API was introduced.

Normal response codes: 201

Error response codes: 400, 401, 403, 409

Request
-------

.. rest_parameters:: parameters.yaml

   - name: runbook_name
   - steps: runbook_steps
   - disable_ramdisk: req_disable_ramdisk
   - uuid: req_uuid
   - extra: req_extra

Request Runbook Step
--------------------

.. rest_parameters:: parameters.yaml

   - interface: runbook_step_interface
   - step: runbook_step_step
   - args: runbook_step_args
   - order: runbook_step_order

Request Example
---------------

.. literalinclude:: samples/runbook-create-request.json
   :language: javascript

Response Parameters
-------------------

.. rest_parameters:: parameters.yaml

   - uuid: uuid
   - name: runbook_name
   - steps: runbook_steps
   - disable_ramdisk: disable_ramdisk
   - extra: extra
   - public: runbook_public
   - owner: runbook_owner
   - created_at: created_at
   - updated_at: updated_at
   - links: links

Response Example
----------------

.. literalinclude:: samples/runbook-create-response.json
   :language: javascript

List Runbooks
=============

.. rest_method::  GET /v1/runbooks

Lists all runbooks.

.. versionadded:: 1.92
    Runbook API was introduced.

Normal response codes: 200

Error response codes: 400, 401, 403, 404

Request
-------

.. rest_parameters:: parameters.yaml

   - fields: fields
   - limit: limit
   - marker: marker
   - sort_dir: sort_dir
   - sort_key: sort_key
   - detail: detail

Response Parameters
-------------------

.. rest_parameters:: parameters.yaml

   - uuid: uuid
   - name: runbook_name
   - disable_ramdisk: disable_ramdisk
   - steps: runbook_steps
   - extra: extra
   - public: runbook_public
   - owner: runbook_owner
   - created_at: created_at
   - updated_at: updated_at
   - links: links

Response Example
----------------

**Example runbook list response:**

.. literalinclude:: samples/runbook-list-response.json
   :language: javascript

**Example detailed runbook list response:**

.. literalinclude:: samples/runbook-detail-response.json
   :language: javascript

Show Runbook Details
====================

.. rest_method::  GET /v1/runbooks/{runbook_id}

Shows details for a runbook.

.. versionadded:: 1.92
    Runbook API was introduced.

Normal response codes: 200

Error response codes: 400, 401, 403, 404

Request
-------

.. rest_parameters:: parameters.yaml

   - fields: fields
   - runbook_id: runbook_ident

Response Parameters
-------------------

.. rest_parameters:: parameters.yaml

   - uuid: uuid
   - name: runbook_name
   - steps: runbook_steps
   - disable_ramdisk: disable_ramdisk
   - extra: extra
   - public: runbook_public
   - owner: runbook_owner
   - created_at: created_at
   - updated_at: updated_at
   - links: links

Response Example
----------------

.. literalinclude:: samples/runbook-show-response.json
   :language: javascript

Update a Runbook
================

.. rest_method:: PATCH /v1/runbooks/{runbook_id}

Update a runbook.

.. versionadded:: 1.92
    Runbook API was introduced.

Normal response code: 200

Error response codes: 400, 401, 403, 404, 409

Request
-------

The BODY of the PATCH request must be a JSON PATCH document, adhering to
`RFC 6902 <https://tools.ietf.org/html/rfc6902>`_.

Request
-------

.. rest_parameters:: parameters.yaml

    - runbook_id: runbook_ident

.. literalinclude:: samples/runbook-update-request.json
   :language: javascript

Response
--------

.. rest_parameters:: parameters.yaml

   - uuid: uuid
   - name: runbook_name
   - steps: runbook_steps
   - disable_ramdisk: disable_ramdisk
   - extra: extra
   - public: runbook_public
   - owner: runbook_owner
   - created_at: created_at
   - updated_at: updated_at
   - links: links

.. literalinclude:: samples/runbook-update-response.json
   :language: javascript

Delete Runbook
==============

.. rest_method::  DELETE /v1/runbooks/{runbook_id}

Deletes a runbook.

.. versionadded:: 1.92
    Runbook API was introduced.

Normal response codes: 204

Error response codes: 400, 401, 403, 404

Request
-------

.. rest_parameters:: parameters.yaml

  - runbook_id: runbook_ident
