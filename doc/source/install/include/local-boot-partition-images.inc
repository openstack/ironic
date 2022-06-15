.. _local-boot-partition-images:

Local boot with partition images
--------------------------------

The Bare Metal service supports local boot with partition images, meaning that
after the deployment the node's subsequent reboots won't happen via PXE or
Virtual Media. Instead, it will boot from a local boot loader installed on
the disk.

.. note:: Whole disk images, on the contrary, support only local boot, and use
          it by default.

It's important to note that in order for this to work the image being
deployed with Bare Metal service **must** contain ``grub2`` installed within it.

Enabling the local boot is different when Bare Metal service is used with
Compute service and without it.
The following sections will describe both methods.

.. _ironic-python-agent: https://docs.openstack.org/ironic-python-agent/latest/


Enabling local boot with Compute service
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

To enable local boot we need to set a capability on the bare metal node,
for example::

    baremetal node set <node-uuid> --property capabilities="boot_option:local"


Nodes having ``boot_option`` set to ``local`` may be requested by adding
an ``extra_spec`` to the Compute service flavor, for example::

    openstack flavor set baremetal --property capabilities:boot_option="local"


.. note::
    If the node is configured to use ``UEFI``, Bare Metal service will create
    an ``EFI partition`` on the disk and switch the partition table format to
    ``gpt``. The ``EFI partition`` will be used later by the boot loader
    (which is installed from the deploy ramdisk).

.. _local-boot-without-compute:

Enabling local boot without Compute
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Since adding ``capabilities`` to the node's properties is only used by
the nova scheduler to perform more advanced scheduling of instances,
we need a way to enable local boot when Compute is not present. To do that
we can simply specify the capability via the ``instance_info`` attribute
of the node, for example::

    baremetal node set <node-uuid> --instance-info capabilities='{"boot_option": "local"}'
