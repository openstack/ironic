.. -*- rst -*-

=================
Drivers (drivers)
=================

A driver is a Python object containing all the logic to manage the bare metal
nodes enrolled within Ironic. A driver may be loaded within one or more
``ironic-conductor`` services. Each driver contains a pre-determined set of
instantiated interfaces. Each type of interface (eg, ``power`` or ``boot``)
performs a specific hardware function.

The REST API exposes the list of drivers and which ``ironic-conductor``
processes have loaded that driver via the Driver resource (``/v1/drivers``
endpoint). This can be useful for operators to validate their configuration in
a heterogeneous hardware environment. Each ``ironic-conductor`` process may
load one or more drivers, and does not necessarily need to load the same
drivers as another ``ironic-conductor``.

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

Normal response codes: 200

Request
-------

Response Parameters
-------------------

The response BODY contains a single key, "drivers", whose value is a list of
drivers supported by this Ironic service.

.. rest_parameters:: parameters.yaml

   - drivers: drivers
   - name: driver_name
   - hosts: hosts
   - links: links
   - properties: driver_property_links

Response Example
----------------

.. literalinclude:: samples/drivers-list-response.json
   :language: javascript


Show driver details
===================

.. rest_method::  GET /v1/drivers/{driver_name}

Shows details for a driver.

Normal response codes: 200

Request
-------

.. rest_parameters:: parameters.yaml

   - driver_name: driver_ident

Response Parameters
-------------------

.. rest_parameters:: parameters.yaml

   - name: driver_name
   - hosts: hosts
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

.. rest_method::  GET /v1/drivers/{driver_name}/raid/logical_disk_properties

Show the required and optional parameters that ``driver_name`` expects to be
supplied in the node's ``raid_config`` field, if a RAID configuration change is
requested.

This resource was added in API microversion 1.12.

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