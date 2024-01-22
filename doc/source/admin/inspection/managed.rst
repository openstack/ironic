Managed and unmanaged inspection
================================

In-band inspection can be *managed* or *unmanaged*. This document explains the
difference between these two concepts and applies both to the built-in in-band
inspection and to :doc:`/admin/inspection/inspector`.

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

For the built-in inspection, the bare metal API endpoint can be overriden
instead:

.. code-block:: ini

   [service_catalog]
   endpoint_override = https://example.com/baremetal

.. _unmanaged-inspection:

Unmanaged inspection
~~~~~~~~~~~~~~~~~~~~

Under *unmanaged* inspection we understand in-band inspection where the boot
configuration (iPXE scripts, DHCP options,  etc) is not provided
by the Bare Metal service. In this case, the node is simply set to boot from
network and powered on. The operator is responsible for the correct network
boot configuration, e.g. as explained in :ref:`configure-unmanaged-inspection`.

Unmanaged inspection was the only inspection mode before the Ussuri release,
and it is still used when the node's boot cannot be configured by the
conductor. The options described above do not affect unmanaged inspection.

Because of the complex installation and operation requirements, unmanaged
inspection is disabled by default. To enable it, set ``require_managed_boot``
to ``False``:

.. code-block:: ini

   [inspector]
   require_managed_boot = False
