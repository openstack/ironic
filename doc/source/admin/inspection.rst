.. _inspection:

===================
Hardware Inspection
===================

Overview
--------

Inspection allows Bare Metal service to discover required node properties
once required ``driver_info`` fields (for example, IPMI credentials) are set
by an operator. Inspection will also create the Bare Metal service ports for the
discovered ethernet MACs. Operators will have to manually delete the Bare Metal
service ports for which physical media is not connected. This is required due
to the `bug 1405131 <https://bugs.launchpad.net/ironic/+bug/1405131>`_.

There are two kinds of inspection supported by Bare Metal service:

#. Out-of-band inspection is currently implemented by several hardware types,
   including ``ilo``, ``idrac`` and ``irmc``.

#. `In-band inspection`_ by utilizing the ironic-inspector_ project.

The node should be in the ``manageable`` state before inspection is initiated.
If it is in the ``enroll`` or ``available`` state, move it to ``manageable``
first::

    baremetal node manage <node_UUID>

Then inspection can be initiated using the following command::

    baremetal node inspect <node_UUID>

.. _capabilities-discovery:

Capabilities discovery
----------------------

This is an incomplete list of capabilities we want to discover during
inspection. The exact support is hardware and hardware type specific though,
the most complete list is provided by the iLO :ref:`ilo-inspection`.

``secure_boot`` (``true`` or ``false``)
    whether secure boot is supported for the node

``boot_mode`` (``bios`` or ``uefi``)
    the boot mode the node is using

``cpu_vt`` (``true`` or ``false``)
    whether the CPU virtualization is enabled

``cpu_aes`` (``true`` or ``false``)
    whether the AES CPU extensions are enabled

``max_raid_level`` (integer, 0-10)
    maximum RAID level supported by the node

``pci_gpu_devices`` (non-negative integer)
    number of GPU devices on the node

The operator can specify these capabilities in nova flavor for node to be selected
for scheduling::

  openstack flavor set my-baremetal-flavor --property capabilities:pci_gpu_devices="> 0"

  openstack flavor set my-baremetal-flavor --property capabilities:secure_boot="true"

Please see a specific :doc:`hardware type page </admin/drivers>` for
the exact list of capabilities this hardware type can discover.

.. _in-band inspection:

In-band inspection
------------------

In-band inspection involves booting a ramdisk on the target node and fetching
information directly from it. This process is more fragile and time-consuming
than the out-of-band inspection, but it is not vendor-specific and works
across a wide range of hardware. In-band inspection is using the
ironic-inspector_ project.

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
