Deploying with anaconda deploy interface
========================================

Ironic supports deploying an OS with the `anaconda`_ installer.
This anaconda deploy interface works with ``pxe`` and ``ipxe`` boot interfaces.

Configuration
-------------

The anaconda deploy interface is not enabled by default. To enable this, add
``anaconda`` to the value of the ``enabled_deploy_interfaces`` configuration
option in ironic.conf. For example:

.. code-block:: ini

   [DEFAULT]
   ...
   enabled_deploy_interfaces = direct,anaconda
   ...

This change takes effect after all the ironic conductors have been
restarted.

The default kickstart template is specified via the configuration option
``[anaconda]default_ks_template``. It is set to this `ks.cfg.template`_
but can be modified to be some other template.

.. code-block::  ini

   [anaconda]
   default_ks_template = file:///etc/ironic/ks.cfg.template


When creating an ironic node, specify ``anaconda`` as the deploy interface.
For example:

.. code-block:: shell

   baremetal node create --driver ipmi \
       --deploy-interface anaconda \
       --boot-interface ipxe

You can also set the anaconda deploy interface via ``--deploy-interface`` on an
existing node:

.. code-block:: shell

   baremetal node set <node> --deploy-interface anaconda


Creating an OS Image
--------------------

While anaconda allows installing individual RPMs, the default kickstart file
expects an OS tarball to be used as the OS image.

This ``baremetal.yum`` file contains all the yum/dnf commands that need to be run
in order to generate the OS tarball. These commands install packages and
package groups that need to be in the image:

.. code-block:: ini

        group install 'Minimal Install'
        install cloud-init
        ts run

An OS tarball can be created using following set of commands, along with the above
``baremetal.yum`` file:

.. code-block:: shell

        export CHROOT=/home/<user>/os-image
        mkdir -p $(CHROOT)
        mkdir -p $(CHROOT)/{dev,proc,run,sys}
        chown -hR root:root $(CHROOT)
        mount --bind /var/cache/yum $(CHROOT)/var/cache/yum
        mount --bind /dev $(CHROOT)/dev
        mount -t proc proc $(CHROOT)/proc
        mount -t tmpfs tmpfs $(CHROOT)/run
        mount -t sysfs sysfs $(CHROOT)/sys
        dnf -y --installroot=$(CHROOT) makecache
        dnf -y --installroot=$(CHROOT) shell baremetal.yum
        rpm --root $(CHROOT) --import $(CHROOT)/etc/pki/rpm-gpg/RPM-GPG-KEY-*
        truncate -s 0 $(CHROOT)/etc/machine-id
        umount $(CHROOT)/var/cache/yum
        umount $(CHROOT)/dev
        umount $(CHROOT)/proc
        umount $(CHROOT)/run
        umount $(CHROOT)/sys
        tar cpzf os-image.tar.gz --xattrs --acls --selinux -C $(CHROOT) .


Configuring the OS Image in glance
----------------------------------

Anaconda is a two-stage installer -- stage 1 consists of the kernel and
ramdisk and stage 2 lives in a squashfs file. All these components can be
found in the CentOS/RHEL/Fedora ISO images.

The kernel and ramdisk can be found at ``/images/pxeboot/vmlinuz`` and
``/images/pxeboot/initrd.img`` respectively in the ISO. The stage 2 squashfs
image can be normally found at ``/LiveOS/squashfs.img`` or
``/images/install.img``.

The OS tarball must be configured with the following properties in glance, in
order to be used with the anaconda deploy driver:

* ``kernel_id``
* ``ramdisk_id``
* ``stage2_id``
* ``disk_file_extension`` (optional)

Valid ``disk_file_extension`` values are ``.img``, ``.tar``, ``.tbz``,
``.tgz``, ``.txz``, ``.tar.gz``, ``.tar.bz2``, and ``.tar.xz``. When
``disk_file_extension`` property is not set to one of the above valid values
the anaconda installer will assume that the image provided is a mountable
OS disk.

This is an example of adding the anaconda-related images and the OS tarball to
glance:

.. code-block:: shell

        openstack image create --file ./vmlinuz --container-format aki \
            --disk-format aki --shared anaconda-kernel-<version>
        openstack image create --file ./initrd.img --container-format ari \
            --disk-format ari --shared anaconda-ramdisk-<version>
        openstack image create --file ./squashfs.img --container-format ari \
            --disk-format ari --shared anaconda-stage-<verison>
        openstack image create --file ./os-image.tar.gz \
            --container-format bare --disk-format raw --shared \
            --property kernel_id=<glance_uuid_vmlinuz> \
            --property ramdisk_id=<glance_uuid_ramdisk> \
            --property stage2_id=<glance_uuid_stage2> disto-name-version \
            --property disk_file_extension=.tgz

Creating a bare metal server
----------------------------

Apart from uploading a custom kickstart template to glance and associating it
with the OS image via the ``ks_template`` property in glance, operators can
also set the kickstart template in the ironic node's ``instance_info`` field.
The kickstart template set in ``instance_info`` takes precedence over the one
specified via the OS image in glance. If no kickstart template is specified
(via the node's ``instance_info``  or ``ks_template`` glance image property),
the default kickstart template will be used to deploy the OS.

This is an example of how to set the kickstart template for a specific
ironic node:

.. code-block:: shell

        openstack baremetal node set <node> \
            --instance_info ks_template=glance://uuid

Limitations
-----------

This deploy interface has only been tested with Red Hat based operating systems
that use anaconda. Other systems are not supported.

.. _`anaconda`: https://fedoraproject.org/wiki/Anaconda
.. _`ks.cfg.template`: https://opendev.org/openstack/ironic/src/branch/master/ironic/drivers/modules/ks.cfg.template
