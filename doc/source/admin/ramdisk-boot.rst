Booting a Ramdisk or an ISO
===========================

Ironic supports booting a user provided ramdisk or an ISO image (starting with
the Victoria release) instead of deploying a node.
Most commonly this is performed when an instance is booted via PXE, iPXE or
Virtual Media, with the only local storage contents being those in memory.
It is supported by ``pxe``, ``ipxe``, ``redfish-virtual-media`` and
``ilo-virtual-media`` boot interfaces.

Configuration
-------------

Ramdisk/ISO boot requires using the ``ramdisk`` deploy interface. It is enabled
by default starting with the Zed release cycle. On an earlier release, it must
be enabled explicitly:

.. code-block:: ini

   [DEFAULT]
   ...
   enabled_deploy_interfaces = direct,ramdisk
   ...

Once enabled and the conductor(s) have been restarted, the interface can
be set upon creation of a new node:

.. code-block:: shell

   baremetal node create --driver ipmi \
       --deploy-interface ramdisk \
       --boot-interface ipxe

or update an existing node:

.. code-block:: shell

   baremetal node set <NODE> --deploy-interface ramdisk

You can also use it with :ref:`redfish virtual media
<redfish-virtual-media-ramdisk>` instead of iPXE.

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
        --instance-info ramdisk=http://path/to/ramdisk.initramfs
    baremetal node deploy <NODE>

.. note::
   Before the Xena release, the ``image_source`` field was also required::

        --instance-info image_source=http://path/to/ramdisk.initramfs

Booting an ISO
--------------

The ``ramdisk`` deploy interface can also be used to boot an ISO image.
For example,

.. code-block:: shell

    baremetal node set <NODE> \
        --instance-info boot_iso=http://path/to/boot.iso
    baremetal node deploy <NODE>

.. note::

   While this interface example utilizes a HTTP URL, as with all fields
   referencing file artifacts in the ``instance_info`` field, a user is
   able to request a file path URL, or an HTTPS URL, or as a Glance Image
   Service object UUID.

.. warning::
   This feature, when utilized with the ``ipxe`` ``boot_interface``,
   will only allow a kernel and ramdisk to be booted from the
   supplied ISO file. Any additional contents, such as additional
   ramdisk contents or installer package files will be unavailable
   after the boot of the Operating System. Operators wishing to leverage
   this functionality for actions such as OS installation should explore
   use of the standard ``ramdisk`` ``deploy_interface`` along with the
   ``instance_info/kernel_append_params`` setting to pass arbitrary
   settings such as a mirror URL for the initial ramdisk to load data from.
   This is a limitation of iPXE and the overall boot process of the
   operating system where memory allocated by iPXE is released.

By default the Bare Metal service will cache the ISO locally and serve from its
HTTP server. If you want to avoid that, set the following:

.. code-block:: shell

    baremetal node set <NODE> \
        --instance-info ramdisk_image_download_source=http

ISO images are also cached across deployments, similarly to how it is done for
normal instance images. The URL together with the last modified response header
are used to determine if an image needs updating.

Limitations
-----------

The intended use case is for advanced scientific and ephemeral workloads
where the step of writing an image to the local storage is not required
or desired. As such, this interface does come with several caveats:

* Configuration drives are not supported with network boot, only with Redfish
  virtual media.
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

Common options
--------------

Disable persistent boot device for ramdisk iso boot
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

For iso boot, Ironic sets the boot target to continuously boot from
the iso attached over virtual media. This behaviour may not always be
desired e.g. if the vmedia is installing to hard drive and then
rebooting. In order to instead set the virtual media to be one time
boot Ironic provides the ``force_persistent_boot_device`` flag in the
node's ``driver_info``. Which can be set to ``Never``::

    $ openstack baremetal node set --driver-info force_persistent_boot_device='Never' <node>

.. _ironic-python-agent-builder: https://opendev.org/openstack/ironic-python-agent-builder
.. _openssh-server: https://docs.openstack.org/diskimage-builder/latest/elements/openssh-server/README.html
.. _devuser: https://docs.openstack.org/diskimage-builder/latest/elements/devuser/README.html
.. _dynamic-login: https://docs.openstack.org/diskimage-builder/latest/elements/dynamic-login/README.html
.. _dhcp-all-interfaces: https://docs.openstack.org/diskimage-builder/latest/elements/dhcp-all-interfaces/README.html
.. _simple-init: https://docs.openstack.org/diskimage-builder/latest/elements/simple-init/README.html
