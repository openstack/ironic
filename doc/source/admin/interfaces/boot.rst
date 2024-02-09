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

The ``pxe`` and ``ipxe`` boot interfaces uses PXE_ or iPXE_ accordingly to
deliver the target kernel/ramdisk pair. PXE uses relatively slow and unreliable
TFTP protocol for transfer, while iPXE uses HTTP. The downside of iPXE is that
it's less common, and usually requires bootstrapping using PXE first.

The ``pxe`` and ``ipxe`` boot interfaces work by preparing a PXE/iPXE
environment for a node on the file system, then instructing the DHCP provider
(for example, the Networking service) to boot the node from it. See
:ref:`direct-deploy-example` for a better understanding of the whole deployment
process.

.. note::
    Both PXE and iPXE are configured differently, when UEFI boot is used
    instead of conventional BIOS boot. This is particularly important for CPU
    architectures that do not have BIOS support at all.

The ``ipxe`` boot interface is used by default for many hardware types,
including ``ipmi``. Some hardware types, notably ``ilo`` and ``irmc`` have
their specific implementations of the PXE boot interface.

Additional configuration is required for this boot interface - see
:doc:`/install/configure-pxe` for details.

HTTP Boot
---------

The ``http`` and ``http-ipxe`` boot interfaces are based upon the Ironic
implementation of the ``pxe`` and ``ipxe`` boot interfaces, respectively,
and utilize HTTP in the transmission of the location to start the
boot sequence from. These interfaces are specific to UEFI as they are rooted
in the UEFI standard v2.5's support for booting from an HTTP URL.

One caveat to keep in mind is that these interfaces require hardware support
and the ability to signal to the remote BMC that the node should boot
utilizing ``UEFIHTTP``. If a hardware type does not support that as an option,
we will fallback and request ``PXE`` boot, but that realistically may only
work if the firmware on the machine is smart enough to check and evaluate
for an HTTP Boot URL instead of a PXE boot server and file name.

It should be noted, that these boot interfaces are available for the vendor
independent, generic hardware types of ``ipmi`` and ``redfish``. Hardware
vendors typically only include additional interfaces after they have performed
their own verification and qualification testing.

Kernel parameters
~~~~~~~~~~~~~~~~~

If you need to pass additional kernel parameters to the deployment/cleaning
ramdisk (for example, to configure serial console), use the following
configuration option:

.. code-block:: ini

    [pxe]
    kernel_append_params = nofb vga=normal

.. note::
   The option was called ``pxe_append_params`` before the Xena cycle.

Per-node and per-instance overrides are also possible, for example:

.. code-block:: bash

  baremetal node set node-0 \
    --driver-info kernel_append_params="nofb vga=normal"
  baremetal node set node-0 \
    --instance-info kernel_append_params="nofb vga=normal"

Starting with the Zed cycle, you can combine the parameters from the
configuration and from the node using the special ``%default%`` syntax:

.. code-block:: bash

  baremetal node set node-0 \
    --driver-info kernel_append_params="%default% console=ttyS0,115200n8"

Together with the configuration above, the following parameters will be
appended to the kernel command line::

    nofb vga=normal console=ttyS0,115200n8

.. note::
   Ironic does not do any de-duplication of the resulting kernel parameters.
   Both kernel itself and dracut seem to give priority to the last instance
   of the same parameter.

.. warning::
   Previously our documentation listed the Linux kernel parameter
   ``nomodeset`` as an option. This option is intended for troubleshooting,
   and can greatly degrade performance with Matrox/Aspeed BMC Graphics
   controllers which is very commonly used on physical servers. The
   performance degradation can greatly reduce IO capacity upon every
   console graphics update being written to the screen.

Common options
--------------

Enable persistent boot device for deploy/clean operation
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

For (i)PXE booting, Ironic uses non-persistent boot order changes for
clean/deploy by default. For some drivers, persistent changes are far
more costly than non-persisent ones, so this approach can bring a
performance benefit.

In order to control this behavior, however, Ironic provides the
``force_persistent_boot_device`` flag in the node's ``driver_info``.
It allows the values ``Default`` (make all changes but the last one
upon deployment non-persistent), ``Always`` (make all changes persistent),
and ``Never`` (make all boot order changes non-persistent). For example
in order to have only persistent changes one would need to set something
like::

    $ openstack baremetal node set --driver-info force_persistent_boot_device='Always' <node>

.. note::
   It is recommended to check if the node's state has not changed as there
   is no way of locking the node between these commands.

.. note::
   The values 'True'/'False' for the option 'force_persistent_boot_device'
   in the node's driver info for the (i)PXE drivers are deprecated and
   support for them may be removed in a future release. The former default
   value 'False' is replaced by the new value 'Default', the value 'True'
   is replaced by 'Always'.


.. _PXE: https://en.wikipedia.org/wiki/Preboot_Execution_Environment
.. _iPXE: https://en.wikipedia.org/wiki/IPXE
.. _management controller: https://en.wikipedia.org/wiki/Out-of-band_management
