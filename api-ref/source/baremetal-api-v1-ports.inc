.. -*- rst -*-

=============
Ports (ports)
=============

Listing, Searching, Creating, Updating, and Deleting of bare metal Port
resources are done through the ``ports`` resource.

All Ports must be associated to a Node when created. This association
can be changed, though the request may be rejected if either the current
or destination Node are in a transitive state (e.g., in the process of
deploying) or are in a state that would be non-deterministically affected by
such a change (e.g., there is an active user instance on the Node).


List Ports
==========

.. rest_method:: GET /v1/ports

Return a list of bare metal Ports. Some filtering is possible by passing in
some parameters with the request.

By default, this query will return the uuid and address for each Port.

.. versionadded:: 1.6
  Added the ``node`` query parameter. If both ``node_uuid`` and ``node`` are
  specified in the request, ``node_uuid`` will be used to filter results.

.. versionadded:: 1.8
  Added the ``fields`` request parameter. When specified, this causes the
  content of the response to include only the specified fields, rather than the
  default set.

.. versionadded:: 1.19
  Added the ``pxe_enabled`` and ``local_link_connection`` fields.

.. versionadded:: 1.24
  Added the ``portgroup_uuid`` field.

.. versionadded:: 1.34
  Added the ``physical_network`` field.

.. versionadded:: 1.43
  Added the ``detail`` boolean request parameter. When specified ``True`` this
  causes the response to include complete details about each port.

.. versionadded:: 1.53
  Added the ``is_smartnic`` field.

Normal response code: 200

Request
-------

.. rest_parameters:: parameters.yaml

    - node: r_port_node_ident
    - node_uuid: r_port_node_uuid
    - portgroup: r_port_portgroup_ident
    - address: r_port_address
    - fields: fields
    - limit: limit
    - marker: marker
    - sort_dir: sort_dir
    - sort_key: sort_key
    - detail: detail

Response
--------

.. rest_parameters:: parameters.yaml

    - ports: ports
    - uuid: uuid
    - address: port_address
    - links: links

**Example Port list response:**

.. literalinclude:: samples/port-list-response.json
   :language: javascript


Create Port
===========

.. rest_method:: POST /v1/ports

Creates a new Port resource.

This method requires a Node UUID and the physical hardware address for the Port
(MAC address in most cases).

.. versionadded:: 1.19
  Added the ``pxe_enabled`` and ``local_link_connection``
  request and response fields.

.. versionadded:: 1.24
  Added the ``portgroup_uuid`` request and response fields.

.. versionadded:: 1.34
  Added the ``physical_network`` request and response fields.

.. versionadded:: 1.53
  Added the ``is_smartnic`` request and response fields.

Normal response code: 201

Request
-------

.. rest_parameters:: parameters.yaml

    - node_uuid: req_node_uuid
    - address: req_port_address
    - portgroup_uuid: req_portgroup_uuid
    - local_link_connection: req_local_link_connection
    - pxe_enabled: req_pxe_enabled
    - physical_network: req_physical_network
    - extra: req_extra
    - is_smartnic: req_is_smartnic
    - uuid: req_uuid

**Example Port creation request:**

.. literalinclude:: samples/port-create-request.json
   :language: javascript

Response
--------

.. rest_parameters:: parameters.yaml

    - uuid: uuid
    - address: port_address
    - node_uuid: node_uuid
    - portgroup_uuid: portgroup_uuid
    - local_link_connection: local_link_connection
    - pxe_enabled: pxe_enabled
    - physical_network: physical_network
    - internal_info: internal_info
    - extra: extra
    - created_at: created_at
    - updated_at: updated_at
    - links: links
    - is_smartnic: is_smartnic

**Example Port creation response:**

.. literalinclude:: samples/port-create-response.json
   :language: javascript


List Detailed Ports
===================

.. rest_method:: GET /v1/ports/detail

Return a list of bare metal Ports, with detailed information.

.. versionadded:: 1.6
  Added the ``node`` query parameter. If both ``node_uuid`` and ``node`` are
  specified in the request, ``node_uuid`` will be used to filter results.

.. versionadded:: 1.19
  Added the ``pxe_enabled`` and ``local_link_connection`` response fields.

.. versionadded:: 1.24
  Added the ``portgroup`` query parameter and ``portgroup_uuid`` response
  field.

.. versionadded:: 1.34
  Added the ``physical_network`` response field.

.. versionadded:: 1.53
  Added the ``is_smartnic`` response fields.

Normal response code: 200

Request
-------

.. rest_parameters:: parameters.yaml

    - node: r_port_node_ident
    - node_uuid: r_port_node_uuid
    - portgroup: r_port_portgroup_ident
    - address: r_port_address
    - limit: limit
    - marker: marker
    - sort_dir: sort_dir
    - sort_key: sort_key

Response
--------

.. rest_parameters:: parameters.yaml

    - ports: ports
    - uuid: uuid
    - address: port_address
    - node_uuid: node_uuid
    - portgroup_uuid: portgroup_uuid
    - local_link_connection: local_link_connection
    - pxe_enabled: pxe_enabled
    - physical_network: physical_network
    - internal_info: internal_info
    - extra: extra
    - created_at: created_at
    - updated_at: updated_at
    - links: links
    - is_smartnic: is_smartnic

**Example detailed Port list response:**

.. literalinclude:: samples/port-list-detail-response.json
   :language: javascript


Show Port Details
=================

.. rest_method:: GET /v1/ports/{port_id}

Show details for the given Port.

.. versionadded:: 1.8
  Added the ``fields`` request parameter. When specified, this causes the
  content of the response to include only the specified fields, rather than the
  default set.

.. versionadded:: 1.19
  Added the ``pxe_enabled`` and ``local_link_connection`` response fields.

.. versionadded:: 1.24
  Added the ``portgroup_uuid`` response field.

.. versionadded:: 1.34
  Added the ``physical_network`` response field.

.. versionadded:: 1.53
  Added the ``is_smartnic`` response fields.

Normal response code: 200

Request
-------

.. rest_parameters:: parameters.yaml

    - port_id: port_ident
    - fields: fields

Response
--------

.. rest_parameters:: parameters.yaml

    - uuid: uuid
    - address: port_address
    - node_uuid: node_uuid
    - portgroup_uuid: portgroup_uuid
    - local_link_connection: local_link_connection
    - pxe_enabled: pxe_enabled
    - physical_network: physical_network
    - internal_info: internal_info
    - extra: extra
    - created_at: created_at
    - updated_at: updated_at
    - links: links
    - is_smartnic: is_smartnic

**Example Port details:**

.. literalinclude:: samples/port-create-response.json
   :language: javascript


Update a Port
=============

.. rest_method:: PATCH /v1/ports/{port_id}

Update a Port.

.. versionadded:: 1.19
  Added the ``pxe_enabled`` and ``local_link_connection`` fields.

.. versionadded:: 1.24
  Added the ``portgroup_uuid`` field.

.. versionadded:: 1.34
  Added the ``physical_network`` field.

.. versionadded:: 1.53
  Added the ``is_smartnic`` fields.

Normal response code: 200

Request
-------

The BODY of the PATCH request must be a JSON PATCH document, adhering to
`RFC 6902 <https://tools.ietf.org/html/rfc6902>`_.

.. rest_parameters:: parameters.yaml

    - port_id: port_ident

**Example Port update request:**

.. literalinclude:: samples/port-update-request.json
   :language: javascript

Response
--------

.. rest_parameters:: parameters.yaml

    - uuid: uuid
    - address: port_address
    - node_uuid: node_uuid
    - portgroup_uuid: portgroup_uuid
    - local_link_connection: local_link_connection
    - pxe_enabled: pxe_enabled
    - physical_network: physical_network
    - internal_info: internal_info
    - extra: extra
    - created_at: created_at
    - updated_at: updated_at
    - links: links
    - is_smartnic: is_smartnic

**Example Port update response:**

.. literalinclude:: samples/port-update-response.json
   :language: javascript


Delete Port
===========

.. rest_method:: DELETE /v1/ports/{port_id}

Delete a Port.

Normal response code: 204

Request
-------

.. rest_parameters:: parameters.yaml

    - port_id: port_ident
