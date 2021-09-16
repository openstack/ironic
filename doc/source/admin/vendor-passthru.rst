Vendor Passthru
===============

The bare metal service allows drivers to expose vendor-specific API known as
*vendor passthru*.

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
endpoint for a particular node,  use CLI:

.. code-block:: console

    $ baremetal node passthru list <redfish-node>
    +-----------------------+------------------------+-------+--------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+------------------------+
    | Name                  | Supported HTTP methods | Async | Description                                                                                                                                                                                            | Response is attachment |
    +-----------------------+------------------------+-------+--------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+------------------------+
    | create_subscription   | POST                   | False | Creates a subscription on a node. Required argument: a dictionary of {'destination': 'destination_url'}                                                                                                | False                  |
    | delete_subscription   | DELETE                 | False | Delete a subscription on a node. Required argument: a dictionary of {'id': 'subscription_bmc_id'}                                                                                                      | False                  |
    | eject_vmedia          | POST                   | True  | Eject a virtual media device. If no device is provided then all attached devices will be ejected. Optional arguments: 'boot_device' - the boot device to eject, either 'cd', 'dvd', 'usb', or 'floppy' | False                  |
    | get_all_subscriptions | GET                    | False | Returns all subscriptions on the node.                                                                                                                                                                 | False                  |
    | get_subscription      | GET                    | False | Get a subscription on the node. Required argument: a dictionary of {'id': 'subscription_bmc_id'}                                                                                                       | False                  |
    +-----------------------+------------------------+-------+--------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+------------------------+

The response will contain information for each method,
such as the method's name, a description, the HTTP methods supported,
and whether it's asynchronous or synchronous.

You can call a method with CLI, for example:

.. code-block:: console

    $ baremetal node passthru call <redfish-node> eject_vmedia

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
vendor_passthru endpoint, use CLI:

.. code-block:: console

   $ baremetal driver passthru list redfish

The response will contain information for each method,
such as the method's name, a description, the HTTP methods supported,
and whether it's asynchronous or synchronous.

.. warning::
   Currently only the methods available in the default interfaces of the
   hardware type are available.

You can call a method with CLI, for example:

.. code-block:: console

    $ baremetal driver passthru call <driver> <method>
