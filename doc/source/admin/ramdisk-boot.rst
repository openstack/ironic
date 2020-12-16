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

Creating a ramdisk
------------------

A ramdisk can be created using the ``ironic-ramdisk-base`` element from
ironic-python-agent-builder_, e.g. with Debian:

.. code-block:: shell

    export ELEMENTS_PATH=/opt/stack/ironic-python-agent-builder/dib
    disk-image-create -o /output/ramdisk \
        debian-minimal ironic-ramdisk-base openssh-server dhcp-all-interfaces

You should consider using the following elements:

* openssh-server_ to install the SSH server since it's not provided by default
  by some minimal images.
* devuser_ or dynamic-login_ to provide SSH access.
* dhcp-all-interfaces_ or simple-init_ to configure networking.

The resulting files (``/output/ramdisk.kernel`` and
``/output/ramdisk.initramfs`` in this case) can then be used when `Booting a
ramdisk`_.

Booting a ramdisk
-----------------

Pass the kernel and ramdisk as normally, also providing the ramdisk as an image
source, for example,

.. code-block:: shell

    baremetal node set <NODE> \
        --instance-info kernel=http://path/to/ramdisk.kernel \
        --instance-info ramdisk=http://path/to/ramdisk.initramfs \
        --instance-info image_source=http://path/to/ramdisk.initramfs
    baremetal node deploy <NODE>

.. note::
   The requirement to pass ``image_source`` is artificial and will be fixed
   in a future version of the Bare Metal service.

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

.. _ironic-python-agent-builder: https://opendev.org/openstack/ironic-python-agent-builder
.. _openssh-server: https://docs.openstack.org/diskimage-builder/latest/elements/openssh-server/README.html
.. _devuser: https://docs.openstack.org/diskimage-builder/latest/elements/devuser/README.html
.. _dynamic-login: https://docs.openstack.org/diskimage-builder/latest/elements/dynamic-login/README.html
.. _dhcp-all-interfaces: https://docs.openstack.org/diskimage-builder/latest/elements/dhcp-all-interfaces/README.html
.. _simple-init: https://docs.openstack.org/diskimage-builder/latest/elements/simple-init/README.html
