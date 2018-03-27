.. _vendor-passthru:

==============
Vendor Methods
==============

This document is a quick tutorial on writing vendor specific methods to
a driver.

The first thing to note is that the Ironic API supports two vendor
endpoints: A driver vendor passthru and a node vendor passthru.

* The ``VendorInterface`` allows hardware types to expose a custom top-level
  functionality which is not specific to a Node. For example, let's say
  the driver `ipmi` exposed a method called `authentication_types`
  that would return what are the authentication types supported. It could
  be accessed via the Ironic API like:

  ::

    GET http://<address>:<port>/v1/drivers/ipmi/vendor_passthru/authentication_types

  .. warning::
      The Bare Metal API currently only allows to use driver passthru for the
      default ``vendor`` interface implementation for a given hardware type.
      This limitation will be lifted in the future.

* The node vendor passthru allows drivers to expose custom functionality
  on per-node basis. For example the same driver `ipmi` exposing a
  method called `send_raw` that would send raw bytes to the BMC, the method
  also receives a parameter called `raw_bytes` which the value would be
  the bytes to be sent. It could be accessed via the Ironic API like:

  ::

    POST {'raw_bytes': '0x01 0x02'} http://<address>:<port>/v1/nodes/<node UUID>/vendor_passthru/send_raw


Writing Vendor Methods
======================

Writing a custom vendor method in Ironic should be simple. The first thing
to do is write a class inheriting from the `VendorInterface`_ class:

.. code-block:: python

  class ExampleVendor(VendorInterface)

      def get_properties(self):
          return {}

      def validate(self, task, **kwargs):
          pass

The `get_properties` is a method that all driver interfaces have, it
should return a dictionary of <property>:<description> telling in the
description whether that property is required or optional so the node
can be manageable by that driver. For example, a required property for a
`ipmi` driver would be `ipmi_address` which is the IP address or hostname
of the node. We are returning an empty dictionary in our example to make
it simpler.

The `validate` method is responsible for validating the parameters passed
to the vendor methods. Ironic will not introspect into what is passed
to the drivers, it's up to the developers writing the vendor method to
validate that data.

Let's extend the `ExampleVendor` class to support two methods, the
`authentication_types` which will be exposed on the driver vendor
passthru endpoint; And the `send_raw` method that will be exposed on
the node vendor passthru endpoint:

.. code-block:: python

  class ExampleVendor(VendorInterface)

      def get_properties(self):
          return {}

      def validate(self, task, method, **kwargs):
          if method == 'send_raw':
              if 'raw_bytes' not in kwargs:
                  raise MissingParameterValue()

      @base.driver_passthru(['GET'], async_call=False)
      def authentication_types(self, context, **kwargs):
          return {"types": ["NONE", "MD5", "MD2"]}

      @base.passthru(['POST'])
      def send_raw(self, task, **kwargs):
          raw_bytes = kwargs.get('raw_bytes')
          ...

That's it!

Writing a node or driver vendor passthru method is pretty much the
same, the only difference is how you decorate the methods and the first
parameter of the method (ignoring self). A method decorated with the
`@passthru` decorator should expect a Task object as first parameter and
a method decorated with the `@driver_passthru` decorator should expect
a Context object as first parameter.

Both decorators accept these parameters:

* http_methods: A list of what the HTTP methods supported by that vendor
  function. To know what HTTP method that function was invoked with, a
  `http_method` parameter will be present in the `kwargs`. Supported HTTP
  methods are *POST*, *PUT*, *GET* and *PATCH*.

* method: By default the method name is the name of the python function,
  if you want to use a different name this parameter is where this name
  can be set. For example:

  .. code-block:: python

    @passthru(['PUT'], method="alternative_name")
    def name(self, task, **kwargs):
        ...

* description: A string containing a nice description about what that
  method is supposed to do. Defaults to "" (empty string).

.. _VendorInterface: ../api/ironic.drivers.base.html#ironic.drivers.base.VendorInterface

* async_call: A boolean value to determine whether this method should run
  asynchronously or synchronously. Defaults to True (Asynchronously).

  .. note:: This parameter was previously called "async".

The node vendor passthru decorator (`@passthru`) also accepts the following
parameter:

* require_exclusive_lock: A boolean value determining whether this method
  should require an exclusive lock on a node between validate() and the
  beginning of method execution. For synchronous methods, the lock on the node
  would also be kept for the duration of method execution. Defaults to True.

.. WARNING::
   Please avoid having a synchronous method for slow/long-running
   operations **or** if the method does talk to a BMC; BMCs are flaky
   and very easy to break.

.. WARNING::
   Each asynchronous request consumes a worker thread in the
   ``ironic-conductor`` process. This can lead to starvation of the
   thread pool, resulting in a denial of service.

Give the new vendor interface implementation a human-friendly name and create
an entry point for it in the ``setup.cfg``::

    ironic.hardware.interfaces.vendor =
        example = ironic.drivers.modules.example:ExampleVendor

Finally, add it to the list of supported vendor interfaces for relevant
hardware types, for example:

.. code-block:: python

    class ExampleHardware(generic.GenericHardware):
        ...

        @property
        def supported_vendor_interfaces(self):
            return [example.ExampleVendor]

Backwards Compatibility
=======================

There is no requirement that changes to a vendor method be backwards
compatible. However, for your users' sakes, we highly recommend that
you do so.

If you are changing the exceptions being raised, you might want to ensure
that the same HTTP code is being returned to the user.

For non-backwards compatibility, please make sure you add a release
note that indicates this.
