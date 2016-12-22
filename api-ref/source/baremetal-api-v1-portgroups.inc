.. -*- rst -*-

=======================
Portgroups (portgroups)
=======================

Starting with API version 1.23 ports can be combined into portgroups to support
static link aggregation group (LAG) or multi-chassis link aggregation group
(MLAG) configurations. Listing, Searching, Creating, Updating, and Deleting of
bare metal Portgroup resources are done through the ``v1/portgroups`` resource.

All Portgroups must be associated with a Node when created. This association
can be changed, though the request may be rejected if either the current
or destination Node are in a transitive state (for example, in the process of
deploying) or are in a state that would be non-deterministically affected by
such a change (for example, there is an active user instance on the Node).


List Portgroups
===============

.. rest_method:: GET /v1/portgroups

Return a list of bare metal Portgroups. Some filtering is possible by passing in
some parameters with the request.

By default, this query will return the UUID, name and address for each Portgroup.

Normal response code: 200

Error codes: 400,401,403,404

Request
-------

.. rest_parameters:: parameters.yaml

    - node: r_portgroup_node_ident
    - address: r_portgroup_address
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

**Example Portgroup list response:**

.. literalinclude:: samples/portgroup-list-response.json
   :language: javascript


Create Portgroup
================

.. rest_method:: POST /v1/portgroups

Creates a new Portgroup resource.

This method requires a Node UUID and the physical hardware address for the
Portgroup (MAC address in most cases).

Normal response code: 201

Error codes: 400,401,403,404

Request
-------

.. rest_parameters:: parameters.yaml

    - node_uuid: node_uuid
    - address: portgroup_address

**Example Portgroup creation request:**

.. literalinclude:: samples/portgroup-create-request.json
   :language: javascript

Response
--------

.. rest_parameters:: parameters.yaml

    - uuid: uuid
    - name: portgroup_name
    - address: portgroup_address
    - node_uuid: node_uuid
    - standalone_ports_supported: standalone_ports_supported
    - internal_info: portgroup_internal_info
    - extra: extra
    - mode: portgroup_mode
    - properties: portgroup_properties
    - created_at: created_at
    - updated_at: updated_at
    - links: links
    - ports: pg_ports

**Example Portgroup creation response:**

.. literalinclude:: samples/portgroup-create-response.json
   :language: javascript


List Detailed Portgroups
========================

.. rest_method:: GET /v1/portgroups/detail

Return a list of bare metal Portgroups, with detailed information.

Normal response code: 200

Error codes: 400,401,403,404

Request
-------

.. rest_parameters:: parameters.yaml

    - node: r_portgroup_node_ident
    - address: r_portgroup_address
    - limit: limit
    - marker: marker
    - sort_dir: sort_dir
    - sort_key: sort_key

Response
--------

.. rest_parameters:: parameters.yaml

    - portgroups: portgroups
    - name: portgroup_name
    - uuid: uuid
    - address: portgroup_address
    - node_uuid: node_uuid
    - standalone_ports_supported: standalone_ports_supported
    - internal_info: portgroup_internal_info
    - extra: extra
    - mode: portgroup_mode
    - properties: portgroup_properties
    - created_at: created_at
    - updated_at: updated_at
    - links: links
    - ports: pg_ports

**Example detailed Portgroup list response:**

.. literalinclude:: samples/portgroup-list-detail-response.json
   :language: javascript


Show Portgroup Details
======================

.. rest_method:: GET /v1/portgroups/{portgroup_id}

Show details for the given Portgroup.

Normal response code: 200

Error codes: 400,401,403,404

Request
-------

.. rest_parameters:: parameters.yaml

    - portgroup_id: portgroup_ident
    - fields: fields

Response
--------

.. rest_parameters:: parameters.yaml

    - uuid: uuid
    - name: portgroup_name
    - address: portgroup_address
    - node_uuid: node_uuid
    - standalone_ports_supported: standalone_ports_supported
    - internal_info: portgroup_internal_info
    - extra: extra
    - mode: portgroup_mode
    - properties: portgroup_properties
    - created_at: created_at
    - updated_at: updated_at
    - links: links
    - ports: pg_ports

**Example Portgroup details:**

.. literalinclude:: samples/portgroup-create-response.json
   :language: javascript


Update a Portgroup
==================

.. rest_method:: PATCH /v1/portgroups/{portgroup_id}

Update a Portgroup.

Normal response code: 200

Error codes: 400,401,403,404

Request
-------

The BODY of the PATCH request must be a JSON PATCH document, adhering to
`RFC 6902 <https://tools.ietf.org/html/rfc6902>`_.

.. rest_parameters:: parameters.yaml

    - portgroup_id: portgroup_ident

**Example Portgroup update request:**

.. literalinclude:: samples/portgroup-update-request.json
   :language: javascript

Response
--------

.. rest_parameters:: parameters.yaml

    - uuid: uuid
    - name: portgroup_name
    - address: portgroup_address
    - node_uuid: node_uuid
    - standalone_ports_supported: standalone_ports_supported
    - internal_info: portgroup_internal_info
    - extra: extra
    - mode: portgroup_mode
    - properties: portgroup_properties
    - created_at: created_at
    - updated_at: updated_at
    - links: links
    - ports: pg_ports

**Example Portgroup update response:**

.. literalinclude:: samples/portgroup-update-response.json
   :language: javascript


Delete Portgroup
================

.. rest_method:: DELETE /v1/portgroups/{portgroup_id}

Delete a Portgroup.

Normal response code: 204

Error codes: 400,401,403,404

Request
-------

.. rest_parameters:: parameters.yaml

    - portgroup_id: portgroup_ident
