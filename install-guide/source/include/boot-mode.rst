.. _boot_mode_support:

Boot mode support
-----------------

The following drivers support setting of boot mode (Legacy BIOS or UEFI).

* ``pxe_ipmitool``

The boot modes can be configured in Bare Metal service in the following way:

* When no boot mode setting is provided, these drivers default the boot_mode
  to Legacy BIOS.

* Only one boot mode (either ``uefi`` or ``bios``) can be configured for
  the node.

* If the operator wants a node to boot always in ``uefi`` mode or ``bios``
  mode, then they may use ``capabilities`` parameter within ``properties``
  field of an bare metal node.  The operator must manually set the appropriate
  boot mode on the bare metal node.

  To configure a node in ``uefi`` mode, then set ``capabilities`` as below::

    ironic node-update <node-uuid> add properties/capabilities='boot_mode:uefi'

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
