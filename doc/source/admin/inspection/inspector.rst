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

There are two modes of in-band inspection: `managed inspection`_ and `unmanaged
inspection`_.

.. _ironic-inspector: https://pypi.org/project/ironic-inspector
.. _python-ironicclient: https://pypi.org/project/python-ironicclient

Managed inspection
~~~~~~~~~~~~~~~~~~

Inspection is *managed* when the Bare Metal conductor fully configures the node
for inspection, including setting boot device, boot mode and power state. This
is the only way to conduct inspection using :ref:`redfish-virtual-media` or
with :doc:`/admin/dhcp-less`. This mode is engaged automatically when the node
has sufficient information to configure boot (e.g. ports in case of iPXE).

There are a few configuration options that tune managed inspection, the most
important is ``extra_kernel_params``, which allows adding kernel parameters for
inspection specifically. This is where you can configure
:ironic-python-agent-doc:`inspection collectors and other parameters
<admin/how_it_works.html#inspection>`, for example:

.. code-block:: ini

   [inspector]
   extra_kernel_params = ipa-inspection-collectors=default,logs ipa-collect-lldp=1

For the callback URL the ironic-inspector endpoint from the service catalog is
used. If you want to override the endpoint for callback only, set the following
option:

.. code-block:: ini

   [inspector]
   callback_endpoint_override = https://example.com/baremetal-introspection/v1/continue

Unmanaged inspection
~~~~~~~~~~~~~~~~~~~~

Under *unmanaged* inspection we understand in-band inspection orchestrated by
ironic-inspector or a third party. This was the only inspection mode before the
Ussuri release, and it is still used when the node's boot cannot be configured
by the conductor. The options described above do not affect unmanaged
inspection. See :ironic-inspector-doc:`ironic-inspector installation guide
<install/index.html>` for more information.

If you want to **prevent** unmanaged inspection from working, set this option:

.. code-block:: ini

   [inspector]
   require_managed_boot = True
