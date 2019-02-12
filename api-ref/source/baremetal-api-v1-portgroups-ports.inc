.. -*- rst -*-

=============================================
Listing Ports by Portgroup (portgroup, ports)
=============================================

.. versionadded:: 1.24

Given a Portgroup identifier (``uuid`` or ``name``), the API exposes the list
of, and details of, all Ports associated with that Portgroup.

These endpoints do not allow modification of the Ports; that should be done
by accessing the Port resources under the ``/v1/ports`` endpoint.

List Ports by Portgroup
=======================

.. rest_method:: GET /v1/portgroups/{portgroup_ident}/ports

Return a list of bare metal Ports associated with ``portgroup_ident``.

When specified, the ``fields`` request parameter causes the content of the
Response to include only the specified fields, rather than the default set.

.. versionadded:: 1.34
  Added the ``physical_network`` field.

.. versionadded:: 1.53
  Added the ``is_smartnic`` response fields.

Normal response code: 200

Error codes: 400,401,403,404

Request
-------

.. rest_parameters:: parameters.yaml

    - portgroup_ident: portgroup_ident
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

**Example list of a Portgroup's Ports:**

.. literalinclude:: samples/portgroup-port-list-response.json


List detailed Ports by Portgroup
================================

.. rest_method:: GET /v1/portgroups/{portgroup_ident}/ports/detail

Return a detailed list of bare metal Ports associated with ``portgroup_ident``.

.. versionadded:: 1.34
  Added the ``physical_network`` field.

.. versionadded:: 1.53
  Added the ``is_smartnic`` response fields.

Normal response code: 200

Error codes: 400,401,403,404

Request
-------

.. rest_parameters:: parameters.yaml

    - portgroup_ident: portgroup_ident
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
    - portgroup_uuid: portgroup_uuid
    - created_at: created_at
    - updated_at: updated_at
    - links: links
    - is_smartnic: is_smartnic

**Example details of a Portgroup's Ports:**

.. literalinclude:: samples/portgroup-port-detail-response.json
