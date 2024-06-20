Configuring an ESP image
========================

An ESP_ image is an image that contains the necessary bootloader to boot the
ISO in UEFI mode. You will need a GRUB2 image file, as well as Shim_ for secure
boot. See :ref:`uefi-pxe-grub` for an explanation how to get them.

Then the following script can be used to build an ESP image:

.. code-block:: bash

   DEST=/path/to/esp.img
   GRUB2=/path/to/grub.efi
   SHIM=/path/to/shim.efi

   dd if=/dev/zero of=$DEST bs=4096 count=1024
   mkfs.msdos -F 12 -n ESP_IMAGE $DEST

   # The following commands require mtools to be installed
   mmd -i $DEST EFI EFI/BOOT
   mcopy -i $DEST -v $SHIM ::EFI/BOOT/BOOTX64.efi
   mcopy -i $DEST -v $GRUB2 ::EFI/BOOT/GRUBX64.efi
   mdir -i $DEST ::EFI/BOOT

.. note::
   If you use an architecture other than x86-64, you'll need to adjust the
   destination paths.

.. warning::
   If you are using secure boot, you *must* utilize the same SHIM and GRUB
   binaries matching your distribution's kernel and ramdisk, otherwise the
   Secure Boot "chain of trust" will be broken.
   Additionally, if you encounter odd issues UEFI booting with virtual media
   which point to the bootloader, verify the appropriate distribution matching
   binaries are in use.

The resulting image should be provided via the ``driver_info/bootloader``
ironic node property in form of an image UUID or a URL:

.. code-block:: bash

   baremetal node set --driver-info bootloader=<glance-uuid-or-url> node-0

Alternatively, set the bootloader UUID or URL in the configuration file:

.. code-block:: ini

   [conductor]
   bootloader = <glance-uuid-or-url>

Finally, you need to provide the correct GRUB2 configuration path for your
image. In most cases this path will depend on your distribution, more
precisely, the distribution you took the GRUB2 image from. For example:

CentOS:

.. code-block:: ini

   [DEFAULT]
   grub_config_path = EFI/centos/grub.cfg

Ubuntu:

.. code-block:: ini

   [DEFAULT]
   grub_config_path = EFI/ubuntu/grub.cfg

.. note::
   Unlike in the script above, these paths are case-sensitive!

.. _ESP: https://wiki.ubuntu.com/EFIBootLoaders#Booting_from_EFI
.. _Shim: https://github.com/rhboot/shim
