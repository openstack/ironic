.. -*- rst -*-

=============
Ports (ports)
=============




Show port details
=================

.. rest_method::  GET /v1/ports/{port_id}

Shows details for a port.


Normal response codes: 200
Error response codes:413,405,404,403,401,400,503,


Request
-------

.. rest_parameters:: parameters.yaml

   - port_id: uuid
   - fields: fields




Response Example
----------------

TODO










Update port
===========

.. rest_method::  PATCH /v1/ports/{port_id}

Updates a port.


Normal response codes: 200
Error response codes:413,415,405,404,403,401,400,503,409,


Request
-------

.. rest_parameters:: parameters.yaml

   - port_id: uuid




Response Example
----------------

TODO












Delete port
===========

.. rest_method::  DELETE /v1/ports/{port_id}

Deletes a port.

Error response codes:204,413,415,405,404,403,401,400,503,409,


Request
-------

.. rest_parameters:: parameters.yaml

   - port_id: uuid















List ports with details
=======================

.. rest_method::  GET /v1/ports/detail

Lists all ports with details.


Normal response codes: 200
Error response codes:413,405,404,403,401,400,503,


Request
-------





Response Example
----------------

TODO










Create port
===========

.. rest_method::  POST /v1/ports

Creates a port.

Error response codes:201,413,415,405,404,403,401,400,503,409,


Request
-------
















List ports
==========

.. rest_method::  GET /v1/ports

Lists all ports.


Normal response codes: 200
Error response codes:413,405,404,403,401,400,503,


Request
-------





Response Example
----------------

TODO









