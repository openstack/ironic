.. -*- rst -*-

=======================
Conductors (conductors)
=======================

.. versionadded:: 1.49

Listing Conductor resources is done through the ``conductors`` resource.

Conductor resources are read-only, they can not be created, updated, or
removed.


List Conductors
===============

.. rest_method:: GET /v1/conductors

Return a list of conductors known by the Bare Metal service.

By default, this query will return the hostname, conductor group, and alive
status for each Conductor. When ``detail`` is set to True in the query string,
will return the full representation of the resource.

Normal response code: 200

Request
-------

.. rest_parameters:: parameters.yaml

    - fields: fields_for_conductor
    - limit: limit
    - marker: marker
    - sort_dir: sort_dir
    - sort_key: sort_key
    - detail: detail

Response
--------

.. rest_parameters:: parameters.yaml

    - hostname: hostname
    - conductor_group: conductor_group
    - alive: alive
    - drivers: drivers
    - links: links

**Example Conductor list response:**

.. literalinclude:: samples/conductor-list-response.json
   :language: javascript

**Example detailed Conductor list response:**

.. literalinclude:: samples/conductor-list-details-response.json
   :language: javascript


Show Conductor Details
======================

.. rest_method::  GET /v1/conductors/{hostname}

Shows details for a conductor. By default, this will return the full
representation of the resource; an optional ``fields`` parameter can be
supplied to return only the specified set.

Normal response codes: 200

Error codes: 400,403,404,406

Request
-------

.. rest_parameters:: parameters.yaml

    - hostname: hostname_ident
    - fields: fields_for_conductor

Response
--------

.. rest_parameters:: parameters.yaml

    - hostname: hostname
    - conductor_group: conductor_group
    - alive: alive
    - drivers: drivers
    - links: links

**Example JSON representation of a Conductor:**

.. literalinclude:: samples/conductor-show-response.json
   :language: javascript
