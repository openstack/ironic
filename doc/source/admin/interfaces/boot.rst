===============
Boot interfaces
===============

The boot interface manages booting of both the deploy ramdisk and the user
instances on the bare metal node.

The `PXE boot`_ interface is generic and works with all hardware that supports
booting from network. Alternatively, several vendors provide *virtual media*
implementations of the boot interface. They work by pushing an ISO image to
the node's `management controller`_, and do not require either PXE or iPXE.
Check your driver documentation at :doc:`../drivers` for details.

.. _pxe-boot:

PXE boot
--------

The ``pxe`` boot interface uses PXE_ or iPXE_ to deliver the target
kernel/ramdisk pair. PXE uses relatively slow and unreliable TFTP protocol
for transfer, while iPXE uses HTTP. The downside of iPXE is that it's less
common, and usually requires bootstrapping using PXE first.

The ``pxe`` boot interface works by preparing a PXE/iPXE environment for a
node on the file system, then instructing the DHCP provider (for example,
the Networking service) to boot the node from it. See
:ref:`iscsi-deploy-example` and :ref:`direct-deploy-example` for a better
understanding of the whole deployment process.

.. note::
    Both PXE and iPXE are configured differently, when UEFI boot is used
    instead of conventional BIOS boot. This is particularly important for CPU
    architectures that do not have BIOS support at all.

The ``pxe`` boot interface is used by default for many hardware types,
including ``ipmi``. Some hardware types, notably ``ilo`` and ``irmc`` have their
specific implementations of the PXE boot interface.

Additional configuration is required for this boot interface - see
:doc:`/install/configure-pxe` for details.

Enable persistent boot device for deploy/clean operation
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Ironic uses non-persistent boot for cleaning/deploying phases as default,
in PXE interface. For some drivers, a persistent change is far more
costly than a non-persistent one, so this can bring performance improvements.

Set the flag ``force_persistent_boot_device`` to ``True`` in the node's
``driver_info``::

    $ openstack baremetal node set --driver-info force_persistent_boot_device=True <node>

.. note::
   It's recommended to check if the node's state has not changed as there
   is no way of locking the node between these commands.

Once the flag is present, the next cleaning and deploy steps will be done
with persistent boot for that node.


.. _PXE: https://en.wikipedia.org/wiki/Preboot_Execution_Environment
.. _iPXE: https://en.wikipedia.org/wiki/IPXE
.. _management controller: https://en.wikipedia.org/wiki/Out-of-band_management
