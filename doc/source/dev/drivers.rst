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

.. toctree::
    ../api/ironic.drivers.agent
    ../api/ironic.drivers.base
    ../api/ironic.drivers.drac
    ../api/ironic.drivers.ilo
    ../api/ironic.drivers.pxe


Node Vendor Passthru
--------------------

Drivers may implement a passthrough API, which becomes accessible via
HTTP POST at the `/v1/{NODE}/vendor_passthru?method={METHOD}` endpoint. Beyond
basic checking, Ironic does not introspect the message body and simply "passes
it through" to the relevant driver.

It should be noted that, while this API end point is asynchronous, it is
serialized.  Requests will return an HTTP status code 202 to indicate the
request was received and is being acted upon, but the request can not return a
BODY. While performing the request, a lock is held on the node, and other
requests will be delayed, and may fail with an HTTP 409 CONFLICT error.

This endpoint is exposing a node's driver directly, and as such, it is
expressly not part of Ironic's standard REST API. There is only a single HTTP
endpoint exposed, and the semantics of the message BODY are determined solely
by the driver. Ironic makes no guarantees about backwards compatibility; this is
solely up to the discretion of each driver's author.

Driver Vendor Passthru
----------------------

Drivers may also implement a similar API for requests not related to any node
at `/v1/drivers/{DRIVER}/vendor_passthru?method={METHOD}`. However, this API
endpoint is *synchronous*. Calls are passed to the driver, and return a BODY
with the response from the driver once the request is completed.

NOTE: Each open request to this endpoint consumes a worker thread within the
ironic-conductor process. This can lead to starvation of the threadpool, and a
denial of service. Driver authors are encouraged to avoid using this endpoint,
and, when necessary, make all requests to it return as quickly as possible.

Similarly, Ironic makes no guarantees about the semantics of the message BODY
sent to this endpoint.  That is left up to each driver's author.
