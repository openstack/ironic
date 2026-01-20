======================
Capabilities discovery
======================

.. _capabilities-discovery:

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

