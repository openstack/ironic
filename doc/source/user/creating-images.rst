Creating instance images
========================

Bare Metal provisioning requires two sets of images: the deploy images
and the user images. The :ref:`deploy images <deploy-ramdisk>` are used by the
Bare Metal service to prepare the bare metal server for actual OS deployment.
Whereas the user images are installed on the bare metal server to be used by
the end user. There are two types of user images:

*partition images*
    contain only the contents of the root partition. Additionally, two more
    images are used together with them when booting from network: an image with
    a kernel and with an initramfs.

    .. warning::
        To use partition images with local boot, Grub2 must be installed on
        them.

*whole disk images*
    contain a complete partition table with one or more partitions.

    .. warning::
        The kernel/initramfs pair must not be used with whole disk images,
        otherwise they'll be mistaken for partition images.

Many distributions publish their own cloud images. These are usually whole disk
images that are built for legacy boot mode (not UEFI), with Ubuntu being an
exception (they publish images that work in both modes).

disk-image-builder
------------------

The `disk-image-builder`_ can be used to create user images required for
deployment and the actual OS which the user is going to run.

- Install diskimage-builder package (use virtualenv, if you don't
  want to install anything globally):

  .. code-block:: console

     # pip install diskimage-builder

- Build the image your users will run (Ubuntu image has been taken as
  an example):

  - Partition images

    .. code-block:: console

       $ disk-image-create ubuntu baremetal dhcp-all-interfaces grub2 -o my-image

  - Whole disk images

    .. code-block:: console

       $ disk-image-create ubuntu vm dhcp-all-interfaces -o my-image

    … with an EFI partition:

    .. code-block:: console

       $ disk-image-create ubuntu vm block-device-efi dhcp-all-interfaces -o my-image

The partition image command creates ``my-image.qcow2``,
``my-image.vmlinuz`` and ``my-image.initrd`` files. The ``grub2`` element
in the partition image creation command is only needed if local boot will
be used to deploy ``my-image.qcow2``, otherwise the images
``my-image.vmlinuz`` and ``my-image.initrd`` will be used for PXE booting
after deploying the bare metal with ``my-image.qcow2``. For whole disk images
only the main image is used.

If you want to use Fedora image, replace ``ubuntu`` with ``fedora`` in the
chosen command.

.. _disk-image-builder: https://docs.openstack.org/diskimage-builder/latest/

Virtual machine
---------------

Virtual machine software can also be used to build user images. There are
different software options available, qemu-kvm is usually a good choice on
linux platform, it supports emulating many devices and even building images
for architectures other than the host machine by software emulation.
VirtualBox is another good choice for non-linux host.

The procedure varies depending on the software used, but the steps for
building an image are similar, the user creates a virtual machine, and
installs the target system just like what is done for a real hardware. The
system can be highly customized like partition layout, drivers or software
shipped, etc.

Usually libvirt and its management tools are used to make interaction with
qemu-kvm easier, for example, to create a virtual machine with
``virt-install``::

    $ virt-install --name centos8 --ram 4096 --vcpus=2 -f centos8.qcow2 \
    > --cdrom CentOS-8-x86_64-1905-dvd1.iso

Graphic frontend like ``virt-manager`` can also be utilized.

The disk file can be used as user image after the system is set up and powered
off. The path of the disk file varies depending on the software used, usually
it's stored in a user-selected part of the local file system. For qemu-kvm or
GUI frontend building upon it, it's typically stored at
``/var/lib/libvirt/images``.

