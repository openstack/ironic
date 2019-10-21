=========================
REST API Conceptual Guide
=========================

Versioning
==========

The ironic REST API supports two types of versioning:

- "major versions", which have dedicated urls.
- "microversions", which can be requested through the use of the
  ``X-OpenStack-Ironic-API-Version`` header.

There is only one major version supported currently, "v1". As such, most URLs
in this documentation are written with the "/v1/" prefix.

Starting with the Kilo release, ironic supports microversions. In this context,
a version is defined as a string of 2 integers separated by a dot: **X.Y**.
Here ``X`` is a major version, always equal to ``1``, and ``Y`` is
a minor version. Server minor version is increased every time the API behavior
is changed (note `Exceptions from Versioning`_).

.. note::
   :nova-doc:`Nova versioning documentation <contributor/microversions.html#when-do-i-need-a-new-microversion>`
   has a nice guide for developers on when to bump an API version.

The server indicates its minimum and maximum supported API versions in the
``X-OpenStack-Ironic-API-Minimum-Version`` and
``X-OpenStack-Ironic-API-Maximum-Version`` headers respectively, returned
with every response. Client may request a specific API version by providing
``X-OpenStack-Ironic-API-Version`` header with request.

The requested microversion determines both the allowable requests and the
response format for all requests. A resource may be represented differently
based on the requested microversion.

If no version is requested by the client, the minimum supported version will be
assumed. In this way, a client is only exposed to those API features that are
supported in the requested (explicitly or implicitly) API version (again note
`Exceptions from Versioning`_, they are not covered by this rule).

We recommend clients that require a stable API to always request a specific
version of API that they have been tested against.

.. note::
    A special value ``latest`` can be requested instead a numerical
    microversion, which always requests the newest supported API version from
    the server.

REST API Versions History
-------------------------

.. toctree::
   :maxdepth: 1

   API Version History <webapi-version-history>


Exceptions from Versioning
--------------------------

The following API-visible things are not covered by the API versioning:

* Current node state is always exposed as it is, even if not supported by the
  requested API version, with exception of ``available`` state, which is
  returned in version 1.1 as ``None`` (in Python) or ``null`` (in JSON).

* Data within free-form JSON attributes: ``properties``, ``driver_info``,
  ``instance_info``, ``driver_internal_info`` fields on a node object;
  ``extra`` fields on all objects.

* Addition of new drivers.

* All vendor passthru methods.
