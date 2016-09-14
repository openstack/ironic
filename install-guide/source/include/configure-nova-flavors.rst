.. _flavor-creation:

Create Compute flavors for use with the Bare Metal service
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

You'll need to create a special bare metal flavor in the Compute service.
The flavor is mapped to the bare metal node through the hardware specifications.

#. Change these to match your hardware:

   .. code-block:: console

      $ RAM_MB=1024
      $ CPU=2
      $ DISK_GB=100
      $ ARCH={i686|x86_64}

#. Create the bare metal flavor by executing the following command:

   .. code-block:: console

      $ nova flavor-create my-baremetal-flavor auto $RAM_MB $DISK_GB $CPU

   .. note:: You can replace ``auto`` with your own flavor id.

#. Set the architecture as extra_specs information of the flavor. This
   will be used to match against the properties of bare metal nodes:

   .. code-block:: console

      $ nova flavor-key my-baremetal-flavor set cpu_arch=$ARCH

#. Associate the deploy ramdisk and kernel images with the ironic node:

   .. code-block:: console

      $ ironic node-update $NODE_UUID add \
          driver_info/deploy_kernel=$DEPLOY_VMLINUZ_UUID \
          driver_info/deploy_ramdisk=$DEPLOY_INITRD_UUID
