.. _drivers:

=================
Pluggable Drivers
=================

Ironic supports a pluggable driver model. This allows contributors to easily
add new drivers, and operators to use third-party drivers or write their own.

Drivers are loaded by the ironic-conductor service during initialization, by
enumerating the python entrypoint "ironic.drivers" and attempting to load
all drivers specified in the "enabled_drivers" configuration option. A
complete list of drivers available on the system may be found by
enumerating this entrypoint by running the following python script::

  #!/usr/bin/env python

  import pkg_resources as pkg
  print [p.name for p in pkg.iter_entry_points("ironic.drivers") if not p.name.startswith("fake")]

A list of drivers enabled in a running Ironic service may be found by issuing
the following command against that API end point::

  ironic driver-list


Supported Drivers
-----------------

For a list of supported drivers (those that are continuously tested on every
upstream commit) please consult the wiki page::

  https://wiki.openstack.org/wiki/Ironic/Drivers

Node Vendor Passthru
--------------------

Drivers may implement a passthrough API, which is accessible via
the ``/v1/nodes/<Node UUID or Name>/vendor_passthru?method={METHOD}``
endpoint. Beyond basic checking, Ironic does not introspect the message
body and simply "passes it through" to the relevant driver.

A method:

* can support one or more HTTP methods (for example, GET, POST)

* is asynchronous or synchronous

  + For asynchronous methods, a 202 (Accepted) HTTP status code is returned
    to indicate that the request was received, accepted and is being acted
    upon. No body is returned in the response.

  + For synchronous methods, a 200 (OK) HTTP status code is returned to
    indicate that the request was fulfilled. The response may include a body.

* can require an exclusive lock on the node. This only occurs if the method
  doesn't specify require_exclusive_lock=False in the decorator. If an
  exclusive lock is held on the node, other requests for the node will be
  delayed and may fail with an HTTP 409 (Conflict) error code.

This endpoint exposes a node's driver directly, and as such, it is
expressly not part of Ironic's standard REST API. There is only a
single HTTP endpoint exposed, and the semantics of the message body
are determined solely by the driver. Ironic makes no guarantees about
backwards compatibility; this is solely up to the discretion of each
driver's author.

To get information about all the methods available via the vendor_passthru
endpoint for a particular node, you can issue an HTTP GET request::

  GET /v1/nodes/<Node UUID or name>/vendor_passthru/methods

The response's JSON body will contain information for each method,
such as the method's name, a description, the HTTP methods supported,
and whether it's asynchronous or synchronous.


Driver Vendor Passthru
----------------------

Drivers may implement an API for requests not related to any node,
at ``/v1/drivers/<driver name>/vendor_passthru?method={METHOD}``.

A method:

* can support one or more HTTP methods (for example, GET, POST)

* is asynchronous or synchronous

  + For asynchronous methods, a 202 (Accepted) HTTP status code is
    returned to indicate that the request was received, accepted and is
    being acted upon. No body is returned in the response.

  + For synchronous methods, a 200 (OK) HTTP status code is returned
    to indicate that the request was fulfilled. The response may include
    a body.

.. note::
  Unlike methods in `Node Vendor Passthru`_, a request does not lock any
  resource, so it will not delay other requests and will not fail with an
  HTTP 409 (Conflict) error code.

Ironic makes no guarantees about the semantics of the message BODY sent
to this endpoint. That is left up to each driver's author.

To get information about all the methods available via the driver
vendor_passthru endpoint, you can issue an HTTP GET request::

  GET /v1/drivers/<driver name>/vendor_passthru/methods

The response's JSON body will contain information for each method,
such as the method's name, a description, the HTTP methods supported,
and whether it's asynchronous or synchronous.
