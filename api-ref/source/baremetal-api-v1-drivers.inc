.. -*- rst -*-

=================
Drivers (drivers)
=================




Show driver details
===================

.. rest_method::  GET /v1/drivers/{driver_name}

Shows details for a driver.


Normal response codes: 200
Error response codes:413,405,404,403,401,400,503,


Request
-------

.. rest_parameters:: parameters.yaml

   - driver_name: driver_name


Response Parameters
-------------------

.. rest_parameters:: parameters.yaml

   - hosts: hosts
   - name: name



Response Example
----------------

.. literalinclude:: samples/driver-get-response.json
   :language: javascript











Show driver properties
======================

.. rest_method::  GET /v1/drivers/{driver_name}/properties

Shows properties for a driver.


Normal response codes: 200
Error response codes:413,405,404,403,401,400,503,


Request
-------

.. rest_parameters:: parameters.yaml

   - driver_name: driver_name


Response Parameters
-------------------

.. rest_parameters:: parameters.yaml

   - hosts: hosts
   - name: name
   - links: links
   - properties: properties



Response Example
----------------

.. literalinclude:: samples/driver-get-response.json
   :language: javascript











List drivers
============

.. rest_method::  GET /v1/drivers

Lists all drivers.


Normal response codes: 200
Error response codes:413,405,404,403,401,400,503,


Request
-------



Response Parameters
-------------------

.. rest_parameters:: parameters.yaml

   - drivers: drivers
   - hosts: hosts
   - name: name



Response Example
----------------

.. literalinclude:: samples/drivers-list-response.json
   :language: javascript











Show driver logical disk properties
===================================

.. rest_method::  GET /v1/drivers/{driver_name}/raid/logical_disk_properties

Shows logical disk properties for a driver.


Normal response codes: 200
Error response codes:413,405,404,403,401,400,503,


Request
-------

.. rest_parameters:: parameters.yaml

   - driver_name: driver_name


Response Parameters
-------------------

.. rest_parameters:: parameters.yaml

   - hosts: hosts
   - name: name
   - links: links
   - properties: properties



Response Example
----------------

.. literalinclude:: samples/driver-get-response.json
   :language: javascript











Show driver vendor methods
==========================

.. rest_method::  GET /v1/drivers/{driver_name}/vendor_passthru/methods

Shows vendor methods for a driver.


Normal response codes: 200
Error response codes:413,405,404,403,401,400,503,


Request
-------

.. rest_parameters:: parameters.yaml

   - driver_name: driver_name


Response Parameters
-------------------

.. rest_parameters:: parameters.yaml

   - hosts: hosts
   - name: name
   - links: links
   - properties: properties



Response Example
----------------

.. literalinclude:: samples/driver-get-response.json
   :language: javascript










