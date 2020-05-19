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

.. versionchanged:: 1.6
  A Node may be referenced both by its UUID and by a unique human-readable
  "name" in any request. Throughout this documentation, this is referred to as
  the ``node_ident``. Responses clearly indicate whether a given field is a
  ``uuid`` or a ``name``.

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

.. versionadded:: 1.2
  Added ``available`` state name, which replaced ``None`` as the status of an
  unprovisioned Node. All clients should be updated to use the new
  ``available`` state name.  Nodes in the ``available`` state may have
  workloads provisioned on them; they are "available" for use.

.. versionadded:: 1.5
  Introduced the ``name`` field.

.. versionadded:: 1.7
  Introduced the ``clean_step`` field.

.. versionchanged:: 1.11
  The default initial state of newly-created Nodes from ``available`` to
  ``enroll``. This provides users a workflow to verify the manageability of a
  Node and perform necessary operational functions (eg, building a RAID array)
  before making the Node available for provisioning.

.. versionadded:: 1.12
  Introduced support for the ``raid_config`` and ``target_raid_config`` fields.

.. versionadded:: 1.20
  Introduced the ``network_interface`` field. If this field is not supplied
  when creating the Node, the default value will be used.

.. versionadded:: 1.21
  Introduced the ``resource_class`` field, which may be used to store a
  resource designation for the proposed OpenStack Placement Engine. This field
  has no effect within Ironic.

.. versionadded:: 1.31
  Introduced the ``boot_interface``, ``deploy_interface``,
  ``management_interface``, ``power_interface``, ``inspect_interface``,
  ``console_interface``, ``vendor_interface`` and ``raid_interface`` fields. If
  any of these fields are not supplied when creating the Node, their default
  value will be used.

.. versionchanged:: 1.31
  If the specified driver is a dynamic driver, then all the interfaces
  (boot_interface, deploy_interface, etc.) will be set to the default interface
  for that driver unless another enabled interface is specified in the creation
  request.

.. versionadded:: 1.33
  Introduced the ``storage_interface`` field. If this field is not supplied
  when creating the Node, the default value will be used.

.. versionadded:: 1.38
  Introduced the ``rescue_interface`` field. If this field is not supplied
  when creating the Node, the default value will be used.

.. versionadded:: 1.44
  Introduced the ``deploy_step`` field.

.. versionadded:: 1.46
  Introduced the ``conductor_group`` field.

.. versionadded:: 1.50
  Introduced the ``owner`` field.

.. versionadded:: 1.51
  Introduced the ``description`` field.

.. versionadded:: 1.52
  Introduced the ``allocation_uuid`` field.

.. versionadded:: 1.65
  Introduced the ``lessee`` field.

Normal response codes: 201

Error codes: 400,403,406

Request
-------

.. rest_parameters:: parameters.yaml

   - boot_interface: req_boot_interface
   - conductor_group: req_conductor_group
   - console_interface: req_console_interface
   - deploy_interface: req_deploy_interface
   - driver_info: req_driver_info
   - driver: req_driver_name
   - extra: req_extra
   - inspect_interface: req_inspect_interface
   - management_interface: req_management_interface
   - name: node_name
   - network_interface: req_network_interface
   - power_interface: req_power_interface
   - properties: req_properties
   - raid_interface: req_raid_interface
   - rescue_interface: req_rescue_interface
   - resource_class: req_resource_class_create
   - storage_interface: req_storage_interface
   - uuid: req_uuid
   - vendor_interface: req_vendor_interface
   - owner: owner
   - description: n_description
   - lessee: lessee

**Example Node creation request with a dynamic driver:**

.. literalinclude:: samples/node-create-request-dynamic.json
   :language: javascript

**Example Node creation request with a classic driver:**

.. literalinclude:: samples/node-create-request-classic.json
   :language: javascript

Response
--------

The response will contain the complete Node record, with the supplied data,
and any defaults added for non-specified fields. Most fields default to "null"
or "".

The list and example below are representative of the response as of API
microversion 1.48.

.. rest_parameters:: parameters.yaml

    - uuid: uuid
    - name: node_name
    - power_state: power_state
    - target_power_state: target_power_state
    - provision_state: provision_state
    - target_provision_state: target_provision_state
    - maintenance: maintenance
    - maintenance_reason: maintenance_reason
    - fault: fault
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
    - deploy_step: deploy_step
    - links: links
    - ports: n_ports
    - portgroups: n_portgroups
    - states: n_states
    - resource_class: resource_class
    - boot_interface: boot_interface
    - console_interface: console_interface
    - deploy_interface: deploy_interface
    - inspect_interface: inspect_interface
    - management_interface: management_interface
    - network_interface: network_interface
    - power_interface: power_interface
    - raid_interface: raid_interface
    - rescue_interface: rescue_interface
    - storage_interface: storage_interface
    - traits: n_traits
    - vendor_interface: vendor_interface
    - volume: n_volume
    - conductor_group: conductor_group
    - protected: protected
    - protected_reason: protected_reason
    - conductor: conductor
    - owner: owner
    - lessee: lessee
    - description: n_description
    - allocation_uuid: allocation_uuid

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

.. versionadded:: 1.8
  Added the ``fields`` Request parameter. When specified,
  this causes the content of the Response to include only the specified fields,
  rather than the default set.

.. versionadded:: 1.9
  Added the ``provision_state`` Request parameter, allowing the list of
  returned Nodes to be filtered by their current state.

.. versionadded:: 1.16
  Added the ``driver`` Request parameter, allowing the list of returned Nodes
  to be filtered by their driver name.

.. versionadded:: 1.21
  Added the ``resource_class`` Request parameter, allowing the list of returned
  Nodes to be filtered by this field.

.. versionadded:: 1.42
  Introduced the ``fault`` field.

.. versionadded:: 1.43
  Added the ``detail`` boolean request parameter. When specified ``True`` this
  causes the response to include complete details about each node, as shown
  in the "List Nodes Detailed" section below.

.. versionadded:: 1.46
  Introduced the ``conductor_group`` request parameter, to allow filtering the
  list of returned nodes by conductor group.

.. versionadded:: 1.49
  Introduced the ``conductor`` request parameter, to allow filtering the
  list of returned nodes by conductor.

.. versionadded:: 1.50
  Introduced the ``owner`` field.

.. versionadded:: 1.51
  Introduced the ``description`` field.

.. versionadded:: 1.65
  Introduced the ``lessee`` field.

Normal response codes: 200

Error codes: 400,403,406

Request
-------

.. rest_parameters:: parameters.yaml

   - instance_uuid: r_instance_uuid
   - maintenance: r_maintenance
   - associated: r_associated
   - provision_state: r_provision_state
   - driver: r_driver
   - resource_class: r_resource_class
   - conductor_group: r_conductor_group
   - conductor: r_conductor
   - fault: r_fault
   - owner: owner
   - lessee: lessee
   - description_contains: r_description_contains
   - fields: fields
   - limit: limit
   - marker: marker
   - sort_dir: sort_dir
   - sort_key: sort_key
   - detail: detail

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

.. deprecated::
   Use ?detail=True query string instead.

Return a list of bare metal Nodes with complete details. Some filtering is
possible by passing in flags with the request.

This method is particularly useful to locate the Node associated to a given
Nova instance, eg. with a request to ``v1/nodes/detail?instance_uuid={NOVA INSTANCE UUID}``

.. versionadded:: 1.37
  Introduced the ``traits`` field.

.. versionadded:: 1.38
  Introduced the ``rescue_interface`` field.

.. versionadded:: 1.42
  Introduced the ``fault`` field.

.. versionadded:: 1.46
  Introduced the ``conductor_group`` field.

.. versionadded:: 1.48
  Introduced the ``protected`` and ``protected_reason`` fields.

.. versionadded:: 1.49
  Introduced the ``conductor`` request parameter and ``conductor`` field.

.. versionadded:: 1.50
  Introduced the ``owner`` field.

.. versionadded:: 1.51
  Introduced the ``description`` field.

.. versionadded:: 1.52
  Introduced the ``allocation_uuid`` field.

.. versionadded:: 1.65
  Introduced the ``lessee`` field.

Normal response codes: 200

Error codes: 400,403,406

Request
-------

.. rest_parameters:: parameters.yaml

   - instance_uuid: r_instance_uuid
   - maintenance: r_maintenance
   - fault: r_fault
   - associated: r_associated
   - provision_state: r_provision_state
   - driver: r_driver
   - resource_class: r_resource_class
   - conductor_group: r_conductor_group
   - conductor: r_conductor
   - owner: owner
   - lessee: lessee
   - description_contains: r_description_contains
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
    - fault: fault
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
    - deploy_step: deploy_step
    - links: links
    - ports: n_ports
    - portgroups: n_portgroups
    - states: n_states
    - resource_class: resource_class
    - boot_interface: boot_interface
    - console_interface: console_interface
    - deploy_interface: deploy_interface
    - inspect_interface: inspect_interface
    - management_interface: management_interface
    - network_interface: network_interface
    - power_interface: power_interface
    - raid_interface: raid_interface
    - rescue_interface: rescue_interface
    - storage_interface: storage_interface
    - traits: n_traits
    - vendor_interface: vendor_interface
    - volume: n_volume
    - conductor_group: conductor_group
    - protected: protected
    - protected_reason: protected_reason
    - owner: owner
    - lessee: lessee
    - description: n_description
    - conductor: conductor
    - allocation_uuid: allocation_uuid
    - retired: retired
    - retired_reason: retired_reason
    - network_data: network_data

**Example detailed list of Nodes:**

.. literalinclude:: samples/nodes-list-details-response.json
   :language: javascript


Show Node Details
=================

.. rest_method::  GET /v1/nodes/{node_ident}

Shows details for a node. By default, this will return the full representation
of the resource; an optional ``fields`` parameter can be supplied to return
only the specified set.

.. versionadded:: 1.37
  Introduced the ``traits`` field.

.. versionadded:: 1.38
  Introduced the ``rescue_interface`` field.

.. versionadded:: 1.42
  Introduced the ``fault`` field.

.. versionadded:: 1.46
  Introduced the ``conductor_group`` field.

.. versionadded:: 1.48
  Introduced the ``protected`` and ``protected_reason`` fields.

.. versionadded:: 1.49
  Introduced the ``conductor`` field

.. versionadded:: 1.50
  Introduced the ``owner`` field.

.. versionadded:: 1.51
  Introduced the ``description`` field.

.. versionadded:: 1.52
  Introduced the ``allocation_uuid`` field.

.. versionadded:: 1.61
  Introduced the ``retired`` and ``retired_reason`` fields.

.. versionadded:: 1.65
  Introduced the ``lessee`` field.

.. versionadded:: 1.66
  Introduced the ``network_data`` field.

Normal response codes: 200

Error codes: 400,403,404,406

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
    - fault: fault
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
    - deploy_step: deploy_step
    - links: links
    - ports: n_ports
    - portgroups: n_portgroups
    - states: n_states
    - resource_class: resource_class
    - boot_interface: boot_interface
    - console_interface: console_interface
    - deploy_interface: deploy_interface
    - inspect_interface: inspect_interface
    - management_interface: management_interface
    - network_interface: network_interface
    - power_interface: power_interface
    - raid_interface: raid_interface
    - rescue_interface: rescue_interface
    - storage_interface: storage_interface
    - traits: n_traits
    - vendor_interface: vendor_interface
    - volume: n_volume
    - conductor_group: conductor_group
    - protected: protected
    - protected_reason: protected_reason
    - owner: owner
    - lessee: lessee
    - description: n_description
    - conductor: conductor
    - allocation_uuid: allocation_uuid

**Example JSON representation of a Node:**

.. literalinclude:: samples/node-show-response.json
   :language: javascript


Update Node
===========

.. rest_method::  PATCH /v1/nodes/{node_ident}

Updates the information stored about a Node.

Note that this endpoint can not be used to request state changes, which are
managed through sub-resources.

.. versionadded:: 1.25
  Introduced the ability to unset a node's chassis UUID.

.. versionadded:: 1.51
  Introduced the ability to set/unset a node's description.

Normal response codes: 200

Error codes: 400,403,404,406,409

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
    - fault: fault
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
    - deploy_step: deploy_step
    - links: links
    - ports: n_ports
    - portgroups: n_portgroups
    - states: n_states
    - resource_class: resource_class
    - boot_interface: boot_interface
    - console_interface: console_interface
    - deploy_interface: deploy_interface
    - inspect_interface: inspect_interface
    - management_interface: management_interface
    - network_interface: network_interface
    - power_interface: power_interface
    - raid_interface: raid_interface
    - rescue_interface: rescue_interface
    - storage_interface: storage_interface
    - traits: n_traits
    - vendor_interface: vendor_interface
    - volume: n_volume
    - conductor_group: conductor_group
    - protected: protected
    - protected_reason: protected_reason
    - owner: owner
    - lessee: lessee
    - description: n_description
    - conductor: conductor
    - allocation_uuid: allocation_uuid

**Example JSON representation of a Node:**

.. literalinclude:: samples/node-update-driver-info-response.json
   :language: javascript


Delete Node
===========

.. rest_method::  DELETE /v1/nodes/{node_ident}

Deletes a node.

Normal response codes: 204

Error codes: 400,403,404,409

Request
-------

.. rest_parameters:: parameters.yaml

   - node_ident: node_ident
