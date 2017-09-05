.. -*- rst -*-

==============================================
Listing Portgroups by Node (nodes, portgroups)
==============================================

.. versionadded:: 1.24

Given a Node identifier (``uuid`` or ``name``), the API exposes the list of,
and details of, all Portgroups associated with that Node.

These endpoints do not allow modification of the Portgroups; that should be
done by accessing the Portgroup resources under the ``/v1/portgroups``
endpoint.

List Portgroups by Node
=======================

.. rest_method:: GET /v1/nodes/{node_ident}/portgroups

Return a list of bare metal Portgroups associated with ``node_ident``.

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

    - portgroups: portgroups
    - uuid: uuid
    - address: portgroup_address
    - name: portgroup_name
    - links: links

**Example list of a Node's Portgroups:**

.. literalinclude:: samples/node-portgroup-list-response.json


List detailed Portgroups by Node
================================

.. rest_method:: GET /v1/nodes/{node_ident}/portgroups/detail

Return a detailed list of bare metal Portgroups associated with ``node_ident``.

Normal response code: 200

Error codes: 400,401,403,404

Request
-------

.. rest_parameters:: parameters.yaml

    - node_ident: node_ident
    - limit: limit
    - marker: marker
    - sort_dir: sort_dir
    - sort_key: sort_key

Response
--------

.. rest_parameters:: parameters.yaml

    - portgroups: portgroups
    - uuid: uuid
    - address: portgroup_address
    - name: portgroup_name
    - node_uuid: node_uuid
    - standalone_ports_supported: standalone_ports_supported
    - internal_info: portgroup_internal_info
    - extra: extra
    - mode: portgroup_mode
    - properties: portgroup_properties
    - ports: pg_ports
    - created_at: created_at
    - updated_at: updated_at
    - links: links

**Example details of a Node's Portgroups:**

.. literalinclude:: samples/node-portgroup-detail-response.json
