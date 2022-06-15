.. _choosing_the_disk_label:

Choosing the disk label
-----------------------

.. note::
   The term ``disk label`` is historically used in Ironic and was taken
   from `parted <https://www.gnu.org/software/parted>`_. Apparently
   everyone seems to have a different word for ``disk label`` - these
   are all the same thing: disk type, partition table, partition map
   and so on...

Ironic allows operators to choose which disk label they want their
bare metal node to be deployed with when Ironic is responsible for
partitioning the disk; therefore choosing the disk label does not apply
when the image being deployed is a ``whole disk image``.

There are some edge cases where someone may want to choose a specific
disk label for the images being deployed, including but not limited to:

* For machines in ``bios`` boot mode with disks larger than 2 terabytes
  it's recommended to use a ``gpt`` disk label. That's because
  a capacity beyond 2 terabytes is not addressable by using the
  MBR partitioning type. But, although GPT claims to be backward
  compatible with legacy BIOS systems `that's not always the case
  <http://www.rodsbooks.com/gdisk/bios.html>`_.

* Operators may want to force the partitioning to be always MBR (even
  if the machine is deployed with boot mode ``uefi``) to avoid breakage
  of applications and tools running on those instances.

The disk label can be configured in two ways; when Ironic is used with
the Compute service or in standalone mode. The following bullet points
and sections will describe both methods:

* When no disk label is provided Ironic will configure it according
  to the boot mode (see :ref:`boot_mode_support`); ``bios`` boot mode will use
  ``msdos`` and ``uefi`` boot mode will use ``gpt``.

* Only one disk label - either ``msdos`` or ``gpt`` - can be configured
  for the node.

When used with Compute service
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

When Ironic is used with the Compute service the disk label should be
set to node's ``properties/capabilities`` field and also to the flavor
which will request such capability, for example::

    baremetal node set <node-uuid> --property capabilities='disk_label:gpt'

As for the flavor::

    openstack flavor set baremetal --property capabilities:disk_label="gpt"

When used in standalone mode
~~~~~~~~~~~~~~~~~~~~~~~~~~~~

When used without the Compute service, the disk label should be set
directly to the node's ``instance_info`` field, as below::

    baremetal node set <node-uuid> --instance-info capabilities='{"disk_label": "gpt"}'
