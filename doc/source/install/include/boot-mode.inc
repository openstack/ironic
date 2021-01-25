.. _boot_mode_support:

Boot mode support
-----------------

Some of the bare metal hardware types (namely, ``redfish``, ``ilo`` and
generic ``ipmi``) support setting  boot mode (Legacy BIOS or UEFI).

.. note::

   Setting boot mode support in generic ``ipmi`` driver is coupled
   with setting boot device. That makes boot mode support in the
   ``ipmi`` driver incomplete.

.. note::

   In this chapter we will distinguish *ironic node* from *bare metal node*.
   The difference is that *ironic node* refers to a logical node, as it is
   configured in ironic, while *bare metal node* indicates the hardware
   machine that ironic is managing.

The following rules apply in order when ironic manages node boot mode:

* If the hardware type (or bare metal node) does not implement reading
  current boot mode of the bare metal node, then ironic assumes that
  boot mode is not set on the bare metal node

* If boot mode is not set on ironic node and bare metal node boot mode
  is unknown (not set, can't be read etc.), ironic node boot mode
  is set to the value of the `[deploy]/default_boot_mode` option

* If boot mode is set on a bare metal node, but is not set on ironic
  node, bare metal node boot mode is set on ironic node

* If boot mode is set on ironic node, but is not set on the bare metal
  node, ironic node boot mode is attempted to be set on the bare metal
  node (failure to set boot mode on the bare metal node will not fail
  ironic node deployment)

* If different boot modes appear on to be set ironic node and on the
  bare metal node, ironic node boot mode is attempted to be set on
  the bare metal node (failure to set boot mode on the bare metal
  node will fail ironic node deployment)

.. warning::

   If a bare metal node does not support setting boot mode, then
   the operator needs to make sure that boot mode configuration is
   consistent between ironic node and the bare metal node.

The boot modes can be configured in the Bare Metal service in the
following way:

* Only one boot mode (either ``uefi`` or ``bios``) can be configured for
  the node.

* If the operator wants a node to boot always in ``uefi`` mode or ``bios``
  mode, then they may use ``capabilities`` parameter within ``properties``
  field of an bare metal node.  The operator must manually set the appropriate
  boot mode on the bare metal node.

  To configure a node in ``uefi`` mode, then set ``capabilities`` as below::

    openstack baremetal node set <node-uuid> --property capabilities='boot_mode:uefi'

  Nodes having ``boot_mode`` set to ``uefi`` may be requested by adding an
  ``extra_spec`` to the Compute service flavor::

    nova flavor-key ironic-test-3 set capabilities:boot_mode="uefi"
    nova boot --flavor ironic-test-3 --image test-image instance-1

  If ``capabilities`` is used in ``extra_spec`` as above, nova scheduler
  (``ComputeCapabilitiesFilter``) will match only bare metal nodes which have
  the ``boot_mode`` set appropriately in ``properties/capabilities``. It will
  filter out rest of the nodes.

  The above facility for matching in the Compute service can be used in
  heterogeneous environments where there is a mix of ``uefi`` and ``bios``
  machines, and operator wants to provide a choice to the user regarding
  boot modes. If the flavor doesn't contain ``boot_mode`` and ``boot_mode``
  is configured for bare metal nodes, then nova scheduler will consider all
  nodes and user may get either ``bios`` or ``uefi`` machine.

Some hardware support setting secure boot mode, see :ref:`secure-boot` for
details.
