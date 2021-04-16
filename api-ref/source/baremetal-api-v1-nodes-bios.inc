.. -*- rst -*-

=================
Node Bios (nodes)
=================

.. versionadded:: 1.40

Given a Node identifier (``uuid`` or ``name``), the API exposes the list of
all Bios settings associated with that Node.

These endpoints do not allow modification of the Bios settings; that should be
done by using ``clean steps``.

List all Bios settings by Node
==============================

.. rest_method:: GET /v1/nodes/{node_ident}/bios

Return a list of Bios settings associated with ``node_ident``.

.. versionadded:: 1.74
  Added additional fields from bios registry which can be retrieved using
  ``?detail=True`` (see detailed response below).
  Added ``fields`` selector to query for particular fields.

Normal response code: 200

Error codes: 404

Request
-------

.. rest_parameters:: parameters.yaml

    - node_ident: node_ident
    - fields: fields
    - detail: detail

Response
--------

.. rest_parameters:: parameters.yaml

    - bios: bios_settings
    - created_at: created_at
    - updated_at: updated_at
    - links: links
    - name: bios_setting_name
    - value: bios_setting_value

**Example list of a Node's Bios settings:**

.. literalinclude:: samples/node-bios-list-response.json

List detailed Bios settings by Node
===================================

.. rest_method:: GET /v1/nodes/{node_ident}/bios/?detail=True

Return a list of detailed Bios settings associated with ``node_ident``.
The detailed list includes the BIOS Attribute Registry information
retrieved via Redfish.

.. versionadded:: 1.74
  Introduced


Normal response code: 200

Error codes: 404

Request
-------

.. rest_parameters:: parameters.yaml

    - node_ident: node_ident

Response
--------

.. rest_parameters:: parameters.yaml

    - bios: bios_settings
    - created_at: created_at
    - updated_at: updated_at
    - links: links
    - name: bios_setting_name
    - value: bios_setting_value
    - attribute_type: bios_setting_attribute_type
    - allowable_values: bios_setting_allowable_values
    - lower_bound: bios_setting_lower_bound
    - max_length: bios_setting_max_length
    - min_length: bios_setting_min_length
    - read_only: bios_setting_read_only
    - reset_required: bios_setting_reset_required
    - unique: bios_setting_unique
    - upper_bound: bios_setting_upper_bound

**Example list of a Node's Bios settings:**

.. literalinclude:: samples/node-bios-list-details-response.json


Show single Bios setting of a Node
==================================

.. rest_method:: GET /v1/nodes/{node_ident}/bios/{bios_setting}

Return the content of the specific bios ``bios_setting`` associated with
``node_ident``.

. versionadded:: 1.74
  Introduced fields from the BIOS registry.

Normal response code: 200

Error codes: 404

Request
-------

.. rest_parameters:: parameters.yaml

    - node_ident: node_ident
    - bios_setting: bios_setting

Response
--------

.. rest_parameters:: parameters.yaml

    - <key>: d_bios_setting
    - created_at: created_at
    - updated_at: updated_at
    - links: links
    - name: bios_setting_name
    - value: bios_setting_value
    - attribute_type: bios_setting_attribute_type
    - allowable_values: bios_setting_allowable_values
    - lower_bound: bios_setting_lower_bound
    - max_length: bios_setting_max_length
    - min_length: bios_setting_min_length
    - read_only: bios_setting_read_only
    - reset_required: bios_setting_reset_required
    - unique: bios_setting_unique
    - upper_bound: bios_setting_upper_bound

**Example details of a Node's Bios setting details:**

.. literalinclude:: samples/node-bios-detail-response.json
