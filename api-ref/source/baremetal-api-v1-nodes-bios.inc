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

**Example list of a Node's Bios settings:**

.. literalinclude:: samples/node-bios-list-response.json


Show single Bios setting of a Node
==================================

.. rest_method:: GET /v1/nodes/{node_ident}/bios/{bios_setting}

Return the content of the specific bios ``bios_setting`` associated with
``node_ident``.

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

**Example details of a Node's Bios setting details:**

.. literalinclude:: samples/node-bios-detail-response.json
