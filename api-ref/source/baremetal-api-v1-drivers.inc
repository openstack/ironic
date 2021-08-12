.. -*- rst -*-

=================
Drivers (drivers)
=================

.. versionchanged:: 1.30
  The REST API now also exposes information about *dynamic* drivers.

Ironic has two types of drivers: *classic* drivers and *dynamic* drivers.

A *classic* driver is a Python object containing all the logic to manage the
bare metal nodes enrolled within Ironic. A driver may be loaded within one or
more ``ironic-conductor`` services. Each driver contains a pre-determined set
of instantiated interfaces. Each type of interface (eg, ``power`` or ``boot``)
performs a specific hardware function.

*Dynamic* drivers are supported via hardware types, which are Python classes
enabled via entry points. Unlike *classic* drivers, which have pre-determined
interfaces, a hardware type may support multiple types of interfaces. For
example, the ``ipmi`` hardware type may support multiple methods for enabling
node console. Which interface a node of a particular hardware type uses is
determined at runtime. This collection of interfaces is called a *dynamic*
driver. For more information about this, see the node API documentation.

The REST API exposes the list of drivers and which ``ironic-conductor``
processes have loaded that driver via the Driver resource (``/v1/drivers``
endpoint). This can be useful for operators to validate their configuration in
a heterogeneous hardware environment. Each ``ironic-conductor`` process may
load one or more drivers, and does not necessarily need to load the same
*classic* drivers as another ``ironic-conductor``. Each ``ironic-conductor``
with the same hardware types must have the same hardware interfaces enabled.

The REST API also exposes details about each driver, such as what properties
must be supplied to a node's ``driver_info`` for that driver to manage
hardware.

Lastly, some drivers may expose methods through a ``driver_vendor_passthru``
endpoint, allowing one to interact with the driver directly (i.e., without
knowing a specific node identifier). For example, this is used by the ironic
python agent ramdisk to get the UUID of the node being deployed/cleaned by
using MAC addresses of the node's network interfaces the agent has discovered.


List drivers
============

.. rest_method::  GET /v1/drivers

Lists all drivers.

.. versionadded:: 1.77
  Added ``fields`` selector to query for particular fields.

Normal response codes: 200

Request
-------

.. rest_parameters:: parameters.yaml

    - type: driver_type
    - detail: driver_detail
    - fields: fields

Response Parameters
-------------------

The response BODY contains a single key, "drivers", whose value is a list of
drivers supported by this Ironic service.

.. rest_parameters:: parameters.yaml

   - drivers: drivers
   - name: driver_name
   - hosts: hosts
   - type: response_driver_type
   - links: links
   - properties: driver_property_links

.. versionchanged:: 1.30
  If the request has the "detail" URL parameter set to true, each
  driver will also include the following fields.

.. rest_parameters:: parameters.yaml

   - default_bios_interface: default_bios_interface
   - default_boot_interface: default_boot_interface
   - default_console_interface: default_console_interface
   - default_deploy_interface: default_deploy_interface
   - default_inspect_interface: default_inspect_interface
   - default_management_interface: default_management_interface
   - default_network_interface: default_network_interface
   - default_power_interface: default_power_interface
   - default_raid_interface: default_raid_interface
   - default_rescue_interface: default_rescue_interface
   - default_storage_interface: default_storage_interface
   - default_vendor_interface: default_vendor_interface
   - enabled_bios_interfaces: enabled_bios_interfaces
   - enabled_boot_interfaces: enabled_boot_interfaces
   - enabled_console_interfaces: enabled_console_interfaces
   - enabled_deploy_interfaces: enabled_deploy_interfaces
   - enabled_inspect_interfaces: enabled_inspect_interfaces
   - enabled_management_interfaces: enabled_management_interfaces
   - enabled_network_interfaces: enabled_network_interfaces
   - enabled_power_interfaces: enabled_power_interfaces
   - enabled_rescue_interfaces: enabled_rescue_interfaces
   - enabled_raid_interfaces: enabled_raid_interfaces
   - enabled_storage_interfaces: enabled_storage_interfaces
   - enabled_vendor_interfaces: enabled_vendor_interfaces

Response Example
----------------

Example for a request with detail=false (the default):

.. literalinclude:: samples/drivers-list-response.json
   :language: javascript

Example for a request with detail=true:

.. literalinclude:: samples/drivers-list-detail-response.json
   :language: javascript

Show driver details
===================

.. rest_method::  GET /v1/drivers/{driver_name}

Shows details for a driver.

.. versionadded:: 1.77
  Added ``fields`` selector to query for particular fields.

Normal response codes: 200

Request
-------

.. rest_parameters:: parameters.yaml

   - driver_name: driver_ident
   - fields: fields

Response Parameters
-------------------

.. rest_parameters:: parameters.yaml

   - name: driver_name
   - hosts: hosts
   - type: response_driver_type
   - default_bios_interface: default_bios_interface
   - default_boot_interface: default_boot_interface
   - default_console_interface: default_console_interface
   - default_deploy_interface: default_deploy_interface
   - default_inspect_interface: default_inspect_interface
   - default_management_interface: default_management_interface
   - default_network_interface: default_network_interface
   - default_power_interface: default_power_interface
   - default_raid_interface: default_raid_interface
   - default_rescue_interface: default_rescue_interface
   - default_storage_interface: default_storage_interface
   - default_vendor_interface: default_vendor_interface
   - enabled_bios_interfaces: enabled_bios_interfaces
   - enabled_boot_interfaces: enabled_boot_interfaces
   - enabled_console_interfaces: enabled_console_interfaces
   - enabled_deploy_interfaces: enabled_deploy_interfaces
   - enabled_inspect_interfaces: enabled_inspect_interfaces
   - enabled_management_interfaces: enabled_management_interfaces
   - enabled_network_interfaces: enabled_network_interfaces
   - enabled_power_interfaces: enabled_power_interfaces
   - enabled_raid_interfaces: enabled_raid_interfaces
   - enabled_rescue_interfaces: enabled_rescue_interfaces
   - enabled_storage_interfaces: enabled_storage_interfaces
   - enabled_vendor_interfaces: enabled_vendor_interfaces
   - links: links
   - properties: driver_property_links

Response Example
----------------

.. literalinclude:: samples/driver-get-response.json
   :language: javascript


Show driver properties
======================

.. rest_method::  GET /v1/drivers/{driver_name}/properties

Shows the required and optional parameters that ``driver_name`` expects to be
supplied in the ``driver_info`` field for every Node it manages.

To check if all required parameters have been supplied to a Node, you should
query the ``/v1/nodes/{node_ident}/validate`` endpoint.

Normal response codes: 200

Request
-------

.. rest_parameters:: parameters.yaml

   - driver_name: driver_ident

Response Example
----------------

The response BODY is a dictionary, but the keys are unique to each driver.
The structure of the response is ``property`` : ``description``.

The following example is returned from the ``agent_ipmitool`` driver.

.. literalinclude:: samples/driver-property-response.json
   :language: javascript


Show driver logical disk properties
===================================

.. versionadded:: 1.12

.. rest_method::  GET /v1/drivers/{driver_name}/raid/logical_disk_properties

Show the required and optional parameters that ``driver_name`` expects to be
supplied in the node's ``raid_config`` field, if a RAID configuration change is
requested.

Normal response codes: 200

Request
-------

.. rest_parameters:: parameters.yaml

   - driver_name: driver_ident

Response Example
----------------

The response BODY is a dictionary, but the keys are unique to each driver.
The structure of the response is ``property`` : ``description``.

The following example is returned from the ``agent_ipmitool`` driver.

.. literalinclude:: samples/driver-logical-disk-properties-response.json
   :language: javascript
