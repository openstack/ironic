Booting a Ramdisk or an ISO
===========================

Ironic supports booting a user provided ramdisk or an ISO image (starting with
the Victoria release) instead of deploying a node.
Most commonly this is performed when an instance is booted via PXE, iPXE or
Virtual Media, with the only local storage contents being those in memory.
It is suported by ``pxe``, ``ipxe``, ``redfish-virtual-media`` and
``ilo-virtual-media`` boot interfaces.

Configuration
-------------

Ramdisk/ISO boot requires using the ``ramdisk`` deploy interface. As with most
non-default interfaces, it must be enabled and set for a node to be utilized:

.. code-block:: ini

   [DEFAULT]
   ...
   enabled_deploy_interfaces = iscsi,direct,ramdisk
   ...

Once enabled and the conductor(s) have been restarted, the interface can
be set upon creation of a new node:

.. code-block:: shell

   openstack baremetal node create --driver ipmi \
       --deploy-interface ramdisk \
       --boot-interface ipxe

or update an existing node:

.. code-block:: shell

   openstack baremetal node set <NODE> --deploy-interface ramdisk

Using virtual media:

.. code-block:: shell

   openstack baremetal node create --driver redfish \
       --deploy-interface ramdisk \
       --boot-interface redfish-virtual-media

.. TODO(dtantsur): document how exactly to create and boot a ramdisk

Booting an ISO
--------------

The ``ramdisk`` deploy interface can also be used to boot an ISO image.
For example,

.. code-block:: shell

    openstack baremetal node set <NODE> \
        --instance-info boot_iso=http://path/to/boot.iso
    openstack baremetal node deploy <NODE>

Limitations
-----------

The intended use case is for advanced scientific and ephemeral workloads
where the step of writing an image to the local storage is not required
or desired. As such, this interface does come with several caveats:

* Configuration drives are not supported.
* Disk image contents are not written to the bare metal node.
* Users and Operators who intend to leverage this interface should
  expect to leverage a metadata service, custom ramdisk images, or the
  ``instance_info/ramdisk_kernel_arguments`` parameter to add options to
  the kernel boot command line.
* When using PXE/iPXE boot, bare metal nodes must continue to have network
  access to PXE and iPXE network resources. This is contrary to most tenant
  networking enabled configurations where this access is restricted to
  the provisioning and cleaning networks
* As with all deployment interfaces, automatic cleaning of the node will
  still occur with the contents of any local storage being wiped between
  deployments.
