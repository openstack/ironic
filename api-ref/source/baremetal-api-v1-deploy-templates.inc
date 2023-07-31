.. -*- rst -*-

===================================
Deploy Templates (deploy_templates)
===================================

The Deploy Template resource represents a collection of Deploy Steps that may
be executed during deployment of a node. A deploy template is matched for a
node if at the time of deployment, the template's name matches a trait in the
node's ``instance_info.traits``.

.. versionadded:: 1.55
    Deploy Template API was introduced.

Create Deploy Template
======================

.. rest_method::  POST /v1/deploy_templates

Creates a deploy template.

.. versionadded:: 1.55
    Deploy Template API was introduced.

Normal response codes: 201

Error response codes: 400, 401, 403, 409

Request
-------

.. rest_parameters:: parameters.yaml

   - name: deploy_template_name
   - steps: deploy_template_steps
   - uuid: req_uuid
   - extra: req_extra

Request Step
------------

.. rest_parameters:: parameters.yaml

   - interface: deploy_template_step_interface
   - step: deploy_template_step_step
   - args: deploy_template_step_args
   - priority: deploy_template_step_priority

Request Example
---------------

.. literalinclude:: samples/deploy-template-create-request.json
   :language: javascript

Response Parameters
-------------------

.. rest_parameters:: parameters.yaml

   - uuid: uuid
   - name: deploy_template_name
   - steps: deploy_template_steps
   - extra: extra
   - created_at: created_at
   - updated_at: updated_at
   - links: links

Response Example
----------------

.. literalinclude:: samples/deploy-template-create-response.json
   :language: javascript

List Deploy Templates
=====================

.. rest_method::  GET /v1/deploy_templates

Lists all deploy templates.

.. versionadded:: 1.55
    Deploy Template API was introduced.

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
   - name: deploy_template_name
   - steps: deploy_template_steps
   - extra: extra
   - created_at: created_at
   - updated_at: updated_at
   - links: links

Response Example
----------------

**Example deploy template list response:**

.. literalinclude:: samples/deploy-template-list-response.json
   :language: javascript

**Example detailed deploy template list response:**

.. literalinclude:: samples/deploy-template-detail-response.json
   :language: javascript

Show Deploy Template Details
============================

.. rest_method::  GET /v1/deploy_templates/{deploy_template_id}

Shows details for a deploy template.

.. versionadded:: 1.55
    Deploy Template API was introduced.

Normal response codes: 200

Error response codes: 400, 401, 403, 404

Request
-------

.. rest_parameters:: parameters.yaml

   - fields: fields
   - deploy_template_id: deploy_template_ident

Response Parameters
-------------------

.. rest_parameters:: parameters.yaml

   - uuid: uuid
   - name: deploy_template_name
   - steps: deploy_template_steps
   - extra: extra
   - created_at: created_at
   - updated_at: updated_at
   - links: links

Response Example
----------------

.. literalinclude:: samples/deploy-template-show-response.json
   :language: javascript

Update a Deploy Template
========================

.. rest_method:: PATCH /v1/deploy_templates/{deploy_template_id}

Update a deploy template.

.. versionadded:: 1.55
    Deploy Template API was introduced.

Normal response code: 200

Error response codes: 400, 401, 403, 404, 409

Request
-------

The BODY of the PATCH request must be a JSON PATCH document, adhering to
`RFC 6902 <https://tools.ietf.org/html/rfc6902>`_.

Request
-------

.. rest_parameters:: parameters.yaml

    - deploy_template_id: deploy_template_ident

.. literalinclude:: samples/deploy-template-update-request.json
   :language: javascript

Response
--------

.. rest_parameters:: parameters.yaml

   - uuid: uuid
   - name: deploy_template_name
   - steps: deploy_template_steps
   - extra: extra
   - created_at: created_at
   - updated_at: updated_at
   - links: links

.. literalinclude:: samples/deploy-template-update-response.json
   :language: javascript

Delete Deploy Template
======================

.. rest_method::  DELETE /v1/deploy_templates/{deploy_template_id}

Deletes a deploy template.

.. versionadded:: 1.55
    Deploy Template API was introduced.

Normal response codes: 204

Error response codes: 400, 401, 403, 404

Request
-------

.. rest_parameters:: parameters.yaml

  - deploy_template_id: deploy_template_ident
