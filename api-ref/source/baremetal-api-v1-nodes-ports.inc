.. -*- rst -*-

====================================
Listing Ports by Node (nodes, ports)
====================================

Given a Node identifier (``uuid`` or ``name``), the API exposes the list of,
and details of, all Ports associated with that Node.

These endpoints do not allow modification of the Ports; that should be done
by accessing the Port resources under the ``/v1/ports`` endpoint.


List Ports by Node
===================

.. rest_method:: GET /v1/nodes/{node_ident}/ports

Return a list of bare metal Ports associated with ``node_ident``.

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

.. versionadded:: 1.53
  Added the ``is_smartnic`` response fields.

Normal response code: 200

Error codes: TBD

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

    - ports: ports
    - uuid: uuid
    - address: port_address
    - links: links

**Example list of a Node's Ports:**

.. literalinclude:: samples/node-port-list-response.json


List detailed Ports by Node
===========================

.. rest_method:: GET /v1/nodes/{node_ident}/ports/detail

Return a detailed list of bare metal Ports associated with ``node_ident``.

.. versionadded:: 1.19
  Added the ``pxe_enabled`` and ``local_link_connection`` fields.

.. versionadded:: 1.24
  Added the ``portgroup_uuid`` field.

.. versionadded:: 1.34
  Added the ``physical_network`` field.

.. versionadded:: 1.53
  Added the ``is_smartnic`` response fields.

Normal response code: 200

Error codes: TBD

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

    - ports: ports
    - uuid: uuid
    - address: port_address
    - node_uuid: node_uuid
    - local_link_connection: local_link_connection
    - pxe_enabled: pxe_enabled
    - physical_network: physical_network
    - internal_info: internal_info
    - extra: extra
    - created_at: created_at
    - updated_at: updated_at
    - links: links
    - is_smartnic: is_smartnic

**Example details of a Node's Ports:**

.. literalinclude:: samples/node-port-detail-response.json
