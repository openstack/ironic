Inspector Support
=================

Ironic supports in-band inspection using the ironic-inspector_ project. This
is the original in-band inspection implementation, which is being gradually
phased out in favour of a similar implementation inside Ironic proper.

It is supported by all hardware types, and used by default, if enabled, by the
``ipmi`` hardware type. The ``inspector`` *inspect* interface has to be
enabled to use it:

.. code-block:: ini

    [DEFAULT]
    enabled_inspect_interfaces = inspector,no-inspect

If the ironic-inspector service is not registered in the service catalog, set
the following option:

.. code-block:: ini

    [inspector]
    endpoint_override = http://inspector.example.com:5050

In order to ensure that ports in Bare Metal service are synchronized with
NIC ports on the node, the following settings in the ironic-inspector
configuration file must be set:

.. code-block:: ini

    [processing]
    add_ports = all
    keep_ports = present

Managed and unmanaged inspection
--------------------------------

There are two modes of in-band inspection: *managed* inspection and *unmanaged*
inspection. See :doc:`/admin/inspection/managed` for more details.

.. _ironic-inspector: https://pypi.org/project/ironic-inspector
.. _python-ironicclient: https://pypi.org/project/python-ironicclient
