.. _image-requirements:

Create and add images to the Image service
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Bare Metal provisioning requires two sets of images: the deploy images
and the user images. The deploy images are used by the Bare Metal service
to prepare the bare metal server for actual OS deployment. Whereas the
user images are installed on the bare metal server to be used by the
end user. Below are the steps to create the required images and add
them to the Image service:

#. Build the user images

   The `disk-image-builder`_ can be used to create user images required for
   deployment and the actual OS which the user is going to run.

   .. _disk-image-builder: https://docs.openstack.org/diskimage-builder/latest/

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
   after deploying the bare metal with ``my-image.qcow2``.

   If you want to use Fedora image, replace ``ubuntu`` with ``fedora`` in the
   chosen command.

#. Add the user images to the Image service

   Load all the images created in the below steps into the Image service,
   and note the image UUIDs in the Image service for each one as it is
   generated.

   - Add the kernel and ramdisk images to the Image service:

     .. code-block:: console

        $ openstack image create my-kernel --public \
          --disk-format aki --container-format aki --file my-image.vmlinuz

     Store the image uuid obtained from the above step as ``MY_VMLINUZ_UUID``.

     .. code-block:: console

        $ openstack image create my-image.initrd --public \
          --disk-format ari --container-format ari --file my-image.initrd

     Store the image UUID obtained from the above step as ``MY_INITRD_UUID``.

   - Add the *my-image* to the Image service which is going to be the OS
     that the user is going to run. Also associate the above created
     images with this OS image. These two operations can be done by
     executing the following command:

     .. code-block:: console

        $ openstack image create my-image --public \
          --disk-format qcow2 --container-format bare --property \
          kernel_id=$MY_VMLINUZ_UUID --property \
          ramdisk_id=$MY_INITRD_UUID --file my-image.qcow2

   .. note:: To deploy a whole disk image, a kernel_id and a ramdisk_id
             shouldn't be associated with the image. For example,

             .. code-block:: console

                $ openstack image create my-whole-disk-image --public \
                  --disk-format qcow2 --container-format bare \
                  --file my-whole-disk-image.qcow2

#. Build or download the deploy images

   The deploy images are used initially for preparing the server (creating disk
   partitions) before the actual OS can be deployed.

   There are several methods to build or download deploy images, please read
   the :ref:`deploy-ramdisk` section.

   The recommended method is to use CoreOS to build deploy images, you will get
   one kernel disk ``coreos_production_pxe.vmlinuz`` and one ram disk
   ``coreos_production_pxe_image-oem.cpio.gz``.

   .. note:: If you want to customize your deploy images, please read `Image Builders <https://docs.openstack.org/ironic-python-agent/latest/install/index.html#image-builders>`_.

#. Add the deploy images to the Image service

   Add the *coreos_production_pxe.vmlinuz* and *coreos_production_pxe_image-oem.cpio.gz*
   images to the Image service:

   .. code-block:: console

      $ openstack image create deploy-vmlinuz --public \
        --disk-format aki --container-format aki \
        --file coreos_production_pxe.vmlinuz

   Store the image UUID obtained from the above step as ``DEPLOY_VMLINUZ_UUID``.

   .. code-block:: console

      $ openstack image create deploy-initrd --public \
        --disk-format ari --container-format ari \
        --file coreos_production_pxe_image-oem.cpio.gz

   Store the image UUID obtained from the above step as ``DEPLOY_INITRD_UUID``.
