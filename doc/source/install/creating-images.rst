Create user images for the Bare Metal service
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Bare Metal provisioning requires two sets of images: the deploy images
and the user images. The :ref:`deploy images <deploy-ramdisk>` are used by the
Bare Metal service to prepare the bare metal server for actual OS deployment.
Whereas the user images are installed on the bare metal server to be used by
the end user. There are two types of user images:

*partition images*
    contain only the contents of the root partition. Additionally, two more
    images are used together with them: an image with a kernel and with
    an initramfs.

    .. warning::
        To use partition images with local boot, Grub2 must be installed on
        them.

*whole disk images*
    contain a complete partition table with one or more partitions.

    .. warning::
        The kernel/initramfs pair must not be used with whole disk images,
        otherwise they'll be mistaken for partition images.

Building user images
^^^^^^^^^^^^^^^^^^^^

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
