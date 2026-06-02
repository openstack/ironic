.. -*- rst -*-

=====================
Node Firmware (nodes)
=====================

.. versionadded:: 1.86

Given a Node identifier (``uuid`` or ``name``), the API exposes the list of
all Firmware Components associated with that Node.

These endpoints do not allow modification of the Firmware Components; that
should be done by using ``clean steps``.

List all Firmware Components by Node
====================================

.. rest_method:: GET /v1/nodes/{node_ident}/firmware

Return a list of Firmware Components associated with ``node_ident``.

Normal response code: 200

Error codes: 404

Request
-------

.. rest_parameters:: parameters.yaml

    - node_ident: node_ident

Response
--------

.. rest_parameters:: parameters.yaml

    - firmware: firmware_components
    - created_at: created_at
    - updated_at: updated_at
    - component: firmware_component
    - initial_version: firmware_component_initial_version
    - current_version: firmware_component_current_version
    - last_version_flashed: firmware_component_last_version_flashed
    - model: firmware_component_model
    - serial_number: firmware_component_serial_number
    - vendor: firmware_component_vendor

.. note::
   The ``vendor``, ``model``, and ``serial_number`` fields are included in
   the response at API microversion 1.114 or higher.  For NIC components the
   values are sourced from the Redfish ``NetworkAdapter`` resource; for BMC
   components only ``model`` is populated from ``Manager.Model``; all three
   fields are ``null`` for BIOS components.

**Example list of a Node's Firmware Components (starting with API microversion 1.114):**

.. literalinclude:: samples/node-firmware-components-list-response.json
