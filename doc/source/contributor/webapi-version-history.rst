========================
REST API Version History
========================

1.60 (Ussuri, master)
---------------------

Added ``owner`` field to the allocation object. The field should match the
``project_id`` of the intended owner. If the ``owner`` field is set, the
allocation process will only match the allocation with a node that has the
same ``owner`` field set.

1.59 (Ussuri, master)
---------------------

Added the ability to specify a ``vendor_data`` dictionary field in the
``configdrive`` parameter submitted with the deployment of a node. The value
is a dictionary which is served as ``vendor_data2.json`` in the config drive.

1.58 (Train, 12.2.0)
--------------------

Added the ability to backfill allocations for already deployed nodes by
creating an allocation with ``node`` set.

1.57 (Train, 12.2.0)
--------------------

Added the following new endpoint for allocation:

* ``PATCH /v1/allocations/<allocation_ident>`` that allows updating ``name``
  and ``extra`` fields for an existing allocation.

1.56 (Stein, 12.1.0)
--------------------

Added the ability for the ``configdrive`` parameter submitted with
the deployment of a node, to include a ``meta_data``, ``network_data``
and ``user_data`` dictionary fields. Ironic will now use the supplied
data to create a configuration drive for the user. Prior uses of the
``configdrive`` field are unaffected.

1.55 (Stein, 12.1.0)
--------------------

Added the following new endpoints for deploy templates:

* ``GET /v1/deploy_templates`` to list all deploy templates.
* ``GET /v1/deploy_templates/<deploy template identifier>`` to retrieve details
  of a deploy template.
* ``POST /v1/deploy_templates`` to create a deploy template.
* ``PATCH /v1/deploy_templates/<deploy template identifier>`` to update a
  deploy template.
* ``DELETE /v1/deploy_templates/<deploy template identifier>`` to delete a
  deploy template.

1.54 (Stein, 12.1.0)
--------------------

Added new endpoints for external ``events``:

* POST /v1/events for creating events. (This endpoint is only intended for
  internal consumption.)

1.53 (Stein, 12.1.0)
--------------------

Added ``is_smartnic`` field to the port object to enable Smart NIC port
creation in addition to local link connection attributes ``port_id`` and
``hostname``.

1.52 (Stein, 12.1.0)
--------------------

Added allocation API, allowing reserving a node for deployment based on
resource class and traits. The new endpoints are:

* ``POST /v1/allocations`` to request an allocation.
* ``GET /v1/allocations`` to list all allocations.
* ``GET /v1/allocations/<ID or name>`` to retrieve the allocation details.
* ``GET /v1/nodes/<ID or name>/allocation`` to retrieve an allocation
  associated with the node.
* ``DELETE /v1/allocations/<ID or name>`` to remove the allocation.
* ``DELETE /v1/nodes/<ID or name>/allocation`` to remove an allocation
  associated with the node.

Also added a new field ``allocation_uuid`` to the node resource.

1.51 (Stein, 12.1.0)
--------------------

Added ``description`` field to the node object to enable operators to store
any information relates to the node. The field is limited to 4096 characters.

1.50 (Stein, 12.1.0)
--------------------

Added ``owner`` field to the node object to enable operators to store
information in relation to the owner of a node. The field is up to 255
characters and MAY be used in a later point in time to allow designation
and deligation of permissions.

1.49 (Stein, 12.0.0)
--------------------

Added new endpoints for retrieving conductors information, and added a
``conductor`` field to node object.

1.48 (Stein, 12.0.0)
--------------------

Added ``protected`` field to the node object to allow protecting deployed nodes
from undeploying, rebuilding or deletion. Also added ``protected_reason``
to specify the reason of making the node protected.

1.47 (Stein, 12.0.0)
--------------------

Added ``automated_clean`` field to the node object, enabling cleaning per node.

1.46 (Rocky, 11.1.0)
--------------------
Added ``conductor_group`` field to the node and the node response,
as well as support to the API to return results by matching
the parameter.

1.45 (Rocky, 11.1.0)
--------------------

Added ``reset_interfaces`` parameter to node's PATCH request, to specify
whether to reset hardware interfaces to their defaults on driver's update.

1.44 (Rocky, 11.1.0)
--------------------

Added ``deploy_step`` to the node object, to indicate the current deploy
step (if any) being performed on the node.

1.43 (Rocky, 11.0.0)
--------------------

Added ``?detail=`` boolean query to the API list endpoints to provide a more
RESTful alternative to the existing ``/nodes/detail`` and similar endpoints.

1.42 (Rocky, 11.0.0)
--------------------

Added ``fault`` to the node object, to indicate currently detected fault on
the node.

1.41 (Rocky, 11.0.0)
--------------------

Added support to abort inspection of a node in the ``inspect wait`` state.

1.40 (Rocky, 11.0.0)
--------------------

Added BIOS properties as sub resources of nodes:

* GET /v1/nodes/<node_ident>/bios
* GET /v1/nodes/<node_ident>/bios/<setting_name>

Added ``bios_interface`` field to the node object to allow getting and
setting the interface.

1.39 (Rocky, 11.0.0)
--------------------

Added ``inspect wait`` to available provision states. A node is shown as
``inspect wait`` instead of ``inspecting`` during asynchronous inspection.

1.38 (Queens, 10.1.0)
---------------------

Added provision_state verbs ``rescue`` and ``unrescue`` along with
the following states: ``rescue``, ``rescue failed``, ``rescue wait``,
``rescuing``, ``unrescue failed``, and ``unrescuing``.  After rescuing
a node, it will be left in the ``rescue`` state running a rescue
ramdisk, configured with the ``rescue_password``, and listening with
ssh on the specified network interfaces. Unrescuing a node will return
it to ``active``.

Added ``rescue_interface`` to the node object, to
allow setting the rescue interface for a dynamic driver.

1.37 (Queens, 10.1.0)
---------------------

Adds support for node traits, with the following new endpoints.

* GET /v1/nodes/<node identifier>/traits lists the traits for a node.

* PUT /v1/nodes/<node identifier>/traits sets all traits for a node.

* PUT /v1/nodes/<node identifier>/traits/<trait> adds a trait to a node.

* DELETE /v1/nodes/<node identifier>/traits removes all traits from a node.

* DELETE /v1/nodes/<node identifier>/traits/<trait> removes a trait from a
  node.

A node's traits are also included the following node query and list responses:

* GET /v1/nodes/<node identifier>

* GET /v1/nodes/detail

* GET /v1/nodes?fields=traits

Traits cannot be specified on node creation, nor can they be updated via a
PATCH request on the node.

1.36 (Queens, 10.0.0)
---------------------

Added ``agent_version`` parameter to deploy heartbeat request for version
negotiation with Ironic Python Agent features.

1.35 (Queens, 9.2.0)
--------------------

Added ability to provide ``configdrive`` when node is updated
to ``rebuild`` provision state.

1.34 (Pike, 9.0.0)
------------------

Adds a ``physical_network`` field to the port object. All ports in a
portgroup must have the same value in their ``physical_network`` field.

1.33 (Pike, 9.0.0)
------------------

Added ``storage_interface`` field to the node object to allow getting and
setting the interface.

Added ``default_storage_interface`` and ``enabled_storage_interfaces``
fields to the driver object to show the information.

1.32 (Pike, 9.0.0)
------------------

Added new endpoints for remote volume configuration:

* GET /v1/volume as a root for volume resources
* GET /v1/volume/connectors for listing volume connectors
* POST /v1/volume/connectors for creating a volume connector
* GET /v1/volume/connectors/<UUID> for showing a volume connector
* PATCH /v1/volume/connectors/<UUID> for updating a volume connector
* DELETE /v1/volume/connectors/<UUID> for deleting a volume connector
* GET /v1/volume/targets for listing volume targets
* POST /v1/volume/targets for creating a volume target
* GET /v1/volume/targets/<UUID> for showing a volume target
* PATCH /v1/volume/targets/<UUID> for updating a volume target
* DELETE /v1/volume/targets/<UUID> for deleting a volume target

Volume resources also can be listed as sub resources of nodes:

* GET /v1/nodes/<node identifier>/volume
* GET /v1/nodes/<node identifier>/volume/connectors
* GET /v1/nodes/<node identifier>/volume/targets

1.31 (Ocata, 7.0.0)
-------------------

Added the following fields to the node object, to allow getting and
setting interfaces for a dynamic driver:

* boot_interface
* console_interface
* deploy_interface
* inspect_interface
* management_interface
* power_interface
* raid_interface
* vendor_interface

1.30 (Ocata, 7.0.0)
-------------------

Added dynamic driver APIs:

* GET /v1/drivers now accepts a ``type`` parameter (optional, one of
  ``classic`` or ``dynamic``), to limit the result to only classic drivers
  or dynamic drivers (hardware types). Without this parameter, both
  classic and dynamic drivers are returned.

* GET /v1/drivers now accepts a ``detail`` parameter (optional, one of
  ``True`` or ``False``), to show all fields for a driver. Defaults to
  ``False``.

* GET /v1/drivers now returns an additional ``type`` field to show if the
  driver is classic or dynamic.

* GET /v1/drivers/<name> now returns an additional ``type`` field to show
  if the driver is classic or dynamic.

* GET /v1/drivers/<name> now returns additional fields that are null for
  classic drivers, and set as following for dynamic drivers:

  * The value of the default_<interface-type>_interface is the entrypoint
    name of the calculated default interface for that type:

    * default_boot_interface
    * default_console_interface
    * default_deploy_interface
    * default_inspect_interface
    * default_management_interface
    * default_network_interface
    * default_power_interface
    * default_raid_interface
    * default_vendor_interface

  * The value of the enabled_<interface-type>_interfaces is a list of
    entrypoint names of the enabled interfaces for that type:

    * enabled_boot_interfaces
    * enabled_console_interfaces
    * enabled_deploy_interfaces
    * enabled_inspect_interfaces
    * enabled_management_interfaces
    * enabled_network_interfaces
    * enabled_power_interfaces
    * enabled_raid_interfaces
    * enabled_vendor_interfaces

1.29 (Ocata, 7.0.0)
-------------------

Add a new management API to support inject NMI,
'PUT /v1/nodes/(node_ident)/management/inject_nmi'.

1.28 (Ocata, 7.0.0)
-------------------

Add '/v1/nodes/<node identifier>/vifs' endpoint for attach, detach and list of VIFs.

1.27 (Ocata, 7.0.0)
-------------------

Add ``soft rebooting`` and ``soft power off`` as possible values
for the ``target`` field of the power state change payload, and
also add ``timeout`` field to it.

1.26 (Ocata, 7.0.0)
-------------------

Add portgroup ``mode`` and ``properties`` fields.

1.25 (Ocata, 7.0.0)
-------------------

Add possibility to unset chassis_uuid from a node.

1.24 (Ocata, 7.0.0)
-------------------

Added new endpoints '/v1/nodes/<node>/portgroups' and '/v1/portgroups/<portgroup>/ports'.
Added new field ``port.portgroup_uuid``.

1.23 (Ocata, 7.0.0)
-------------------

Added '/v1/portgroups/ endpoint.

1.22 (Newton, 6.1.0)
--------------------

Added endpoints for deployment ramdisks.

1.21 (Newton, 6.1.0)
--------------------

Add node ``resource_class`` field.

1.20 (Newton, 6.1.0)
--------------------

Add node ``network_interface`` field.

1.19 (Newton, 6.1.0)
--------------------

Add ``local_link_connection`` and ``pxe_enabled`` fields to the port object.

1.18 (Newton, 6.1.0)
--------------------

Add ``internal_info`` readonly field to the port object, that will be used
by ironic to store internal port-related information.

1.17 (Newton, 6.0.0)
--------------------

Addition of provision_state verb ``adopt`` which allows an operator
to move a node from ``manageable`` state to ``active`` state without
performing a deployment operation on the node. This is intended for
nodes that have already been deployed by external means.

1.16 (Mitaka, 5.0.0)
--------------------

Add ability to filter nodes by driver.

1.15 (Mitaka, 5.0.0)
--------------------

Add ability to do manual cleaning when a node is in the manageable
provision state via PUT v1/nodes/<identifier>/states/provision,
target:clean, clean_steps:[...].

1.14 (Liberty, 4.2.0)
---------------------

Make the following endpoints discoverable via Ironic API:

* '/v1/nodes/<UUID or logical name>/states'
* '/v1/drivers/<driver name>/properties'

1.13 (Liberty, 4.2.0)
---------------------

Add a new verb ``abort`` to the API used to abort nodes in
``CLEANWAIT`` state.

1.12 (Liberty, 4.2.0)
---------------------

This API version adds the following abilities:

* Get/set ``node.target_raid_config`` and to get
  ``node.raid_config``.
* Retrieve the logical disk properties for the driver.

1.11 (Liberty, 4.0.0, breaking change)
--------------------------------------

Newly registered nodes begin in the ``enroll`` provision state by default,
instead of ``available``. To get them to the ``available`` state,
the ``manage`` action must first be run to verify basic hardware control.
On success the node moves to ``manageable`` provision state. Then the
``provide`` action must be run. Automated cleaning of the node is done and
the node is made ``available``.

1.10 (Liberty, 4.0.0)
---------------------

Logical node names support all RFC 3986 unreserved characters.
Previously only valid fully qualified domain names could be used.

1.9 (Liberty, 4.0.0)
--------------------

Add ability to filter nodes by provision state.

1.8 (Liberty, 4.0.0)
--------------------

Add ability to return a subset of resource fields.

1.7 (Liberty, 4.0.0)
--------------------

Add node ``clean_step`` field.

1.6 (Kilo)
----------

Add :ref:`inspection` process: introduce ``inspecting`` and ``inspectfail``
provision states, and ``inspect`` action that can be used when a node is in
``manageable`` provision state.

1.5 (Kilo)
----------

Add logical node names that can be used to address a node in addition to
the node UUID. Name is expected to be a valid `fully qualified domain
name`_ in this version of API.

1.4 (Kilo)
----------

Add ``manageable`` state and ``manage`` transition, which can be used to
move a node to ``manageable`` state from ``available``.
The node cannot be deployed in ``manageable`` state.
This change is mostly a preparation for future inspection work
and introduction of ``enroll`` provision state.

1.3 (Kilo)
----------

Add node ``driver_internal_info`` field.

1.2 (Kilo, breaking change)
---------------------------

Renamed NOSTATE (``None`` in Python, ``null`` in JSON) node state to
``available``. This is needed to reduce confusion around ``None`` state,
especially when future additions to the state machine land.

1.1 (Kilo)
----------

This was the initial version when API versioning was introduced.
Includes the following changes from Kilo release cycle:

* Add node ``maintenance_reason`` field and an API endpoint to
  set/unset the node maintenance mode.

* Add sync and async support for vendor passthru methods.

* Vendor passthru endpoints support different HTTP methods, not only
  ``POST``.

* Make vendor methods discoverable via the Ironic API.

* Add logic to store the config drive passed by Nova.

This has been the minimum supported version since versioning was
introduced.

1.0 (Juno)
----------

This version denotes Juno API and was never explicitly supported, as API
versioning was not implemented in Juno, and 1.1 became the minimum
supported version in Kilo.

.. _fully qualified domain name: https://en.wikipedia.org/wiki/Fully_qualified_domain_name
