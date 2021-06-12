Deploying with anaconda deploy interface
========================================

Ironic supports deploying OS with anaconda installer in addition to IPA. This
deploy interface supports ``pxe``, ``ipxe`` boot interfaces.

Configuration
-------------

The anaconda deploy interface is not enabled by default. To enable this, use
the ``enabled_deploy_interfaces`` configuration option in ironic.conf

.. code-block:: ini

   [DEFAULT]
   ...
   enabled_deploy_interfaces = direct,anaconda
   ...

This change will not be effective until all Ironic conductors have been
restarted.

.. code-block:: shell

   baremetal node create --driver ipmi \
       --deploy-interface anaconda \
       --boot-interface ipxe

You can also set ``--deploy-interface`` on an existing node:

.. code-block:: shell

   baremetal node set <NODE> --deploy-interface anaconda


Creating an OS Image
--------------------

While anaconda allows installing individual RPMs the default kickstart file
expects a OS tarball to be used as the OS image.

A baremetal.yum file that lists all yum/dnf commands that need to be run to
generate the OS tarball. The commands normally install packages and package'
groups that need to be in the image

.. code-block:: ini

        group install 'Minimal Install'
        install cloud-init
        ts run

An OS tarball can be created using following set of commands using above
baremetal.yum file

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

Anaconda is a two stage installer - The stage1 consists of the kernel and
ramdisk and the stage2 lives in a squashfs file. All these components can be
found in the CentOS/RHEL/Fedora ISO images.

The kernel and ramdisk can be found at ``/images/pxeboot/vmlinuz`` and
``/images/pxeboot/initrd.img`` respectively in the  ISO. The stage2 squashfs
image can be normally found at ``/LiveOS/squashfs.img`` or
``/images/install.img``.

The OS tarball must be configured with following properties in glance to be
used with anaconda deploy driver

    1. ``kernel_id``
    2. ``ramdisk_id``
    3. ``stage2_id``

.. code-block:: shell

        openstack image create --file ./vmlinuz --container-format aki \
            --disk-format aki --shared anaconda-kernel-<version>
        openstack image create --file ./initrd.img --container-format ari \
            --disk-format ari --shared anaconda-ramdisk-<version>
        openstack image create --file ./squashfs.img --container-format ari \
            --disk-format ari --shared anaconda-stage-<verison>
        openstack image create --file ./os-image.tar.gz --container-format \
            compressed --disk-format raw --shared \
            --property kernel_id=<glance_uuid_vmlinuz> \
            --property ramdisk_id=<glance_uuid_ramdisk> \
            --property stage2_id=<glance_uuid_stage2> <disto-name-version>

Creating a baremetal server
---------------------------

Apart from uploading a custom kickstart template to glance and associating it
to the OS Image as ``ks_template`` property in glance, operators can also set
the kickstart template in instance_info. The kickstart template set in
instance_info takes precedence over the one set in the glance image. If
kickstart template is not found in instance_info or the glance image property
the default kickstart template will be used to deploy the OS.

.. code-block:: shell

        openstack baremetal node set $NODE_UUID \
            --instance_info ks_template=glance://uuid

Limitations
-----------

This deploy interface has only been tested with Red Hat based operating systems
that use anaconda. Other systems are not supported.
