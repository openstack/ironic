.. -*- rst -*-

============
API versions
============

Concepts
========

In order to bring new features to users over time, the Ironic API
supports versioning. There are two kinds of versions in Ironic.

- ''major versions'', which have dedicated urls.
- ''microversions'', which can be requested through the use of the
  ``X-OpenStack-Ironic-API-Version`` header or the new standard singular header
  ``OpenStack-API-Version: baremetal <version>``.

The Version APIs work differently from other APIs as they *do not* require authentication.

Upon the Dalmatian release, all API requests support the
new standard singular header ``OpenStack-API-Version: baremetal <version>``.
If that's not present, we fall back to the legacy headers.

Beginning with the Kilo release, all API requests support the
``X-OpenStack-Ironic-API-Version`` header. This header SHOULD be supplied
with every request; in the absence of this header, each request is treated
as though coming from an older pre-Kilo client. This was done to preserve
backwards compatibility as we introduced new features in the server.

If you try to use a feature with an API version older than when that feature
was introduced the ironic service will respond as would before that feature
existed. For example if a new API URL was added, and you try to make a request
with an older API version, then you will get a ``Not Found (404)`` error, or if
a new field was added to an existing API and you request an older API version
then you will get an ``Invalid Parameter`` response.

List API versions
=================

.. rest_method::  GET /

This fetches all the information about all known major API versions in the
deployment. Links to more specific information will be provided for each major
API version, as well as information about supported min and max microversions.

Normal response codes: 200

Request
-------

Response Example
----------------

.. rest_parameters::  parameters.yaml

    - description: description
    - versions: versions
    - version: version
    - id: id
    - links: links
    - min_version: x-openstack-ironic-api-min-version

.. literalinclude:: samples/api-root-response.json
   :language: javascript


Show v1 API
===========

.. rest_method::  GET /v1/

Show all the resources within the Ironic v1 API.

Normal response codes: 200

Request
-------

Response Example
----------------

.. rest_parameters::  parameters.yaml

    - id: id
    - links: links
    - openstack-request-id: openstack-request-id
    - x-openstack-ironic-api-version: header_version
    - x-openstack-ironic-api-min-version: x-openstack-ironic-api-min-version
    - x-openstack-ironic-api-max-version: x-openstack-ironic-api-max-version

.. literalinclude:: samples/api-v1-root-response.json
   :language: javascript
