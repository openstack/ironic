.. -*- rst -*-

=============
Nodes (nodes)
=============

List, Searching, Creating, Updating, and Deleting of bare metal Node resources
are done through the ``/v1/nodes`` resource. There are also several sub-resources,
which allow further actions to be performed on a bare metal Node.

A Node is the canonical representation of a discretely allocatable server,
capable of running an Operating System. Each Node must be associated with a
``driver``; this informs Ironic what protocol to use when managing the Node.

Beginning with API microversion 1.6, a Node may be referenced both by its UUID
and by a unique human-readable "name" in any request. Throughout this
documentation, this is referred to as the ``node_ident``. Responses clearly
indicate whether a given field is a ``uuid`` or a ``name``.

Depending on the Roles assigned to the authenticated OpenStack User, and upon
the configuration of the Bare Metal service, API responses may change. For
example, the default value of the "show_password" settings cause all API
responses to mask passwords within ``driver_info`` with the literal string
"\*\*\*\*\*\*".

Create Node
===========

.. rest_method::  POST /v1/nodes

Creates a new Node resource.

This method requires that a ``driver`` be supplied in the request body.  Most
subresources of a Node (eg, ``properties``, ``driver_info``, etc) may be
supplied when the Node is created, or the resource may be updated later.

API microversion 1.2 introduced the new ``available`` state name, which replaced
``None`` as the status of an unprovisioned Node. All clients should be updated to
use the new ``available`` state name.

Nodes in the ``available`` state may have workloads provisioned on them; they are
"available" for use.

API microversion 1.11 changed the default initial state of newly-created Nodes
from ``available`` to ``enroll``. This provides users a workflow to verify the
manageability of a Node and perform necessary operational functions (eg, building
a RAID array) before making the Node available for provisioning.

Normal response codes: 201

.. TODO: add error codes

Request
-------

.. rest_parameters:: parameters.yaml

   - driver: r_driver_name

**Example Node creation request:**

.. literalinclude:: samples/node-create-request.json
   :language: javascript

Response
--------

The response will contain the complete Node record, with the supplied data,
and any defaults added for non-specified fields. Most fields default to "null"
or "".

API microversion 1.5 introduced the ``name`` field.

API microversion 1.7 introduced the ``clean_step`` field`

API microversion 1.12 introduced support for the ``raid_config`` and
``target_raid_config`` fields.

API microversion 1.20 introduced the ``network_interface`` field. If this field
is not supplied when creating the Node, the default value will be used.

API microversion 1.21 introduced the ``resource_class`` field, which may be used to
store a resource designation for the proposed OpenStack Placement Engine. This
field has no effect within Ironic.


The list and example below are representative of the response as of API microversion 1.22.

.. rest_parameters:: parameters.yaml

    - uuid: uuid
    - name: node_name
    - power_state: power_state
    - target_power_state: target_power_state
    - provision_state: provision_state
    - target_provision_state: target_provision_state
    - maintenance: maintenance
    - maintenance_reason: maintenance_reason
    - last_error: last_error
    - reservation: reservation
    - driver: driver_name
    - driver_info: driver_info
    - driver_internal_info: driver_internal_info
    - properties: n_properties
    - instance_info: instance_info
    - instance_uuid: instance_uuid
    - chassis_uuid: chassis_uuid
    - extra: extra
    - console_enabled: console_enabled
    - raid_config: raid_config
    - target_raid_config: target_raid_config
    - clean_step: clean_step
    - links: links
    - ports: n_ports
    - states: n_states
    - network_interface: network_interface
    - resource_class: resource_class

**Example JSON representation of a Node:**

.. literalinclude:: samples/node-create-response.json
   :language: javascript


List Nodes
==========

.. rest_method::  GET /v1/nodes

Return a list of bare metal Nodes, with some useful information about
each Node. Some filtering is possible by passing in flags with the request.

By default, this query will return the name, uuid, instance uuid, power state,
provision state, and maintenance setting for each Node.

API microversion 1.8 added the ``fields`` Request parameter. When specified,
this causes the content of the Response to include only the specified fields,
rather than the default set.

API microversion 1.9 added the ``provision_state`` Request parameter, allowing
the list of returned Nodes to be filtered by their current state.

API microversion 1.16 added the ``driver`` Request parameter, allowing
the list of returned Nodes to be filtered by their driver name.

API microversion 1.21 added the ``resource_class`` Request parameter,
allowing the list of returned Nodes to be filtered by this field.

Normal response codes: 200

.. TODO: add error codes

Request
-------

.. rest_parameters:: parameters.yaml

   - instance_uuid: r_instance_uuid
   - maintenance: r_maintenance
   - associated: r_associated
   - provision_state: r_provision_state
   - driver: r_driver
   - resource_class: r_resource_class
   - fields: fields
   - limit: limit
   - marker: marker
   - sort_dir: sort_dir
   - sort_key: sort_key

Response
--------

.. rest_parameters:: parameters.yaml

    - uuid: uuid
    - name: node_name
    - instance_uuid: instance_uuid
    - power_state: power_state
    - provision_state: provision_state
    - maintenance: maintenance
    - links: links

**Example list of Nodes:**

.. literalinclude:: samples/nodes-list-response.json
   :language: javascript


List Nodes Detailed
===================

.. rest_method::  GET /v1/nodes/detail

Return a list of bare metal Nodes with complete details. Some filtering is
possible by passing in flags with the request.

This method is particularly useful to locate the Node associated to a given
Nova instance, eg. with a request to ``v1/nodes/detail?instance_uuid={NOVA INSTANCE UUID}``

Normal response codes: 200

.. TODO: add error codes

Request
-------

.. rest_parameters:: parameters.yaml

   - instance_uuid: r_instance_uuid
   - maintenance: r_maintenance
   - associated: r_associated
   - provision_state: r_provision_state
   - driver: r_driver
   - resource_class: r_resource_class
   - limit: limit
   - marker: marker
   - sort_dir: sort_dir
   - sort_key: sort_key

Response
--------

.. rest_parameters:: parameters.yaml

    - uuid: uuid
    - name: node_name
    - power_state: power_state
    - target_power_state: target_power_state
    - provision_state: provision_state
    - target_provision_state: target_provision_state
    - maintenance: maintenance
    - maintenance_reason: maintenance_reason
    - last_error: last_error
    - reservation: reservation
    - driver: driver_name
    - driver_info: driver_info
    - driver_internal_info: driver_internal_info
    - properties: n_properties
    - instance_info: instance_info
    - instance_uuid: instance_uuid
    - chassis_uuid: chassis_uuid
    - extra: extra
    - console_enabled: console_enabled
    - raid_config: raid_config
    - target_raid_config: target_raid_config
    - clean_step: clean_step
    - links: links
    - ports: n_ports
    - states: n_states
    - network_interface: network_interface
    - resource_class: resource_class

**Example detailed list of Nodes:**

.. literalinclude:: samples/nodes-list-details-response.json
   :language: javascript


Show Node Details
=================

.. rest_method::  GET /v1/nodes/{node_ident}

Shows details for a node. By default, this will return the full representation
of the resource; an optional ``fields`` parameter can be supplied to return
only the specified set.

Normal response codes: 200

.. TODO: add error codes

Request
-------

.. rest_parameters:: parameters.yaml

    - node_ident: node_ident
    - fields: fields

Response
--------

.. rest_parameters:: parameters.yaml

    - uuid: uuid
    - name: node_name
    - power_state: power_state
    - target_power_state: target_power_state
    - provision_state: provision_state
    - target_provision_state: target_provision_state
    - maintenance: maintenance
    - maintenance_reason: maintenance_reason
    - last_error: last_error
    - reservation: reservation
    - driver: driver_name
    - driver_info: driver_info
    - driver_internal_info: driver_internal_info
    - properties: n_properties
    - instance_info: instance_info
    - instance_uuid: instance_uuid
    - chassis_uuid: chassis_uuid
    - extra: extra
    - console_enabled: console_enabled
    - raid_config: raid_config
    - target_raid_config: target_raid_config
    - clean_step: clean_step
    - links: links
    - ports: n_ports
    - states: n_states
    - network_interface: network_interface
    - resource_class: resource_class

**Example JSON representation of a Node:**

.. literalinclude:: samples/node-show-response.json
   :language: javascript


Update Node
===========

.. rest_method::  PATCH /v1/nodes/{node_ident}

Updates the information stored about a Node.

Note that this endpoint can not be used to request state changes, which are
managed through sub-resources.

Normal response codes: 200

.. TODO: add error codes

Request
-------

The BODY of the PATCH request must be a JSON PATCH document, adhering to
`RFC 6902 <https://tools.ietf.org/html/rfc6902>`_.

.. rest_parameters:: parameters.yaml

   - node_ident: node_ident

**Example PATCH document updating Node driver_info:**

.. literalinclude:: samples/node-update-driver-info-request.json

Response
--------

.. rest_parameters:: parameters.yaml

    - uuid: uuid
    - name: node_name
    - power_state: power_state
    - target_power_state: target_power_state
    - provision_state: provision_state
    - target_provision_state: target_provision_state
    - maintenance: maintenance
    - maintenance_reason: maintenance_reason
    - last_error: last_error
    - reservation: reservation
    - driver: driver_name
    - driver_info: driver_info
    - driver_internal_info: driver_internal_info
    - properties: n_properties
    - instance_info: instance_info
    - instance_uuid: instance_uuid
    - chassis_uuid: chassis_uuid
    - extra: extra
    - console_enabled: console_enabled
    - raid_config: raid_config
    - target_raid_config: target_raid_config
    - clean_step: clean_step
    - links: links
    - ports: n_ports
    - states: n_states
    - network_interface: network_interface
    - resource_class: resource_class

**Example JSON representation of a Node:**

.. literalinclude:: samples/node-update-driver-info-response.json
   :language: javascript


Delete Node
===========

.. rest_method::  DELETE /v1/nodes/{node_ident}

Deletes a node.

Normal response codes: 204

.. TODO: add error codes

Request
-------

.. rest_parameters:: parameters.yaml

   - node_ident: node_ident
