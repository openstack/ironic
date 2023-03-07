.. -*- rst -*-

==============
Node inventory
==============

.. versionadded:: 1.81

Given a Node identifier, the API provides access to the introspection data
associated to the Node via ``v1/nodes/{node_ident}/inventory`` endpoint.

The format inventory comes from ironic-python-agent and is currently documented
in the `agent inventory documentation
<https://docs.openstack.org/ironic-python-agent/latest/admin/how_it_works.html#hardware-inventory>`_.

Show Node Inventory
===================

.. rest_method:: GET /v1/nodes/{node_ident}/inventory

Normal response code: 200

Error codes:
    - 404 (NodeNotFound, InventoryNotRecorded)

Request
-------

.. rest_parameters:: parameters.yaml

   - node_ident: node_ident

Response
--------

.. rest_parameters:: parameters.yaml

   - inventory: n_inventory
   - plugin_data: n_plugin_data

**Example of inventory from a node:**

.. literalinclude:: samples/node-inventory-response.json
   :language: javascript
