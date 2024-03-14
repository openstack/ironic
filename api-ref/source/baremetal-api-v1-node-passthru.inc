.. -*- rst -*-

============================
Node Vendor Passthru (nodes)
============================

Each driver MAY support vendor-specific extensions, called "passthru" methods.

Internally, Ironic's driver API supports flexibly exposing functions via the
common HTTP methods GET, PUT, POST, and DELETE. To call a passthru method,
the query string must contain the name of the method, eg.
``/vendor_passthru?method=reset_bmc``. The contents of the HTTP request are
forwarded to the Node's driver and validated there.

Ironic's REST API provides a means to discover these methods, but does not provide
support, testing, or documentation for these endpoints. The Ironic development
team does not guarantee any compatibility within these methods between releases,
though we encourage driver authors to provide documentation and support for them.

Besides the endpoints documented here, all other resources and endpoints
under the heading ``vendor_passthru`` should be considered
unsupported APIs, and could be changed without warning by the driver authors.


List Methods
============

.. rest_method:: GET /v1/nodes/{node_ident}/vendor_passthru/methods

Retrieve a list of the available vendor passthru methods for the given Node. The
response will indicate which HTTP method(s) each vendor passthru method allows,
whether the method call will be synchronous or asynchronous, and whether the
response will include any attachment.

Normal response code: 200

.. TODO: add error codes

Request
-------

.. rest_parameters:: parameters.yaml

    - node_ident: node_ident

Response
--------

**Example passthru methods listing:**

.. literalinclude:: samples/node-vendor-passthru-response.json


Call a Method
=============

.. rest_method:: METHOD /v1/nodes/{node_ident}/vendor_passthru?method={method_name}

The HTTP METHOD may be one of GET, POST, PUT, DELETE, depending on the driver
and method.

This endpoint passes the request directly to the Node's hardware driver. The
HTTP BODY must be parseable JSON, which will be converted to parameters passed
to that function. Unparsable JSON, missing parameters, or excess parameters
will cause the request to be rejected with an HTTP 400 error.

Normal response code: 200 202

.. TODO: add error codes

Request
-------

.. rest_parameters:: parameters.yaml

    - node_ident: node_ident
    - method_name: method_name

All other parameters should be passed in the BODY. Parameter list varies by method_name.

Response
--------

Varies.