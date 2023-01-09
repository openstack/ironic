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

.. warning::
   In the Ironic Project terminology, the word ``template`` often refers to
   a file which is supplied to the deployment, which Ironic supplies
   parameters to render a specific output. One critical example of this in
   the Ironic workflow, specifically with this driver, is that the generated
   ``agent token`` is conveyed to the booting ramdisk, facilitating it to call
   back to Ironic and indicate the state. This token is randomly generated
   for every deploy, and is required. Specifically this is leveraged in the
   template's ``pre``, ``onerror``, and ``post`` steps.
   For more infomation on Agent Token, please see :doc:`/admin/agent-token`.

Standalone deployments
----------------------

While this deployment interface driver was developed around the use of other
OpenStack services, it is not explicitly required. For example HTTP(S) URLs
can be supplied by the API user to explictly set the expected baremetal node
``instance_info`` fields

.. code-block:: shell

        baremetal node set <node> \
           --instance_info image_source=<Mirror URL> \
           --instance_info kernel=<Kernel URL> \
           --instance_info ramdisk=<Initial Ramdisk URL> \
           --instance_info stage2=<Installer Stage2 Ramdisk URL>

When doing so, you may wish to also utilize a customized kickstart template,
which can also be a URL. Please reference the ironic community provided
template *ks.cfg.template* and use it as a basis of your own kickstart
as it accounts for the particular stages and appropriate callbacks to
Ironic.

.. warning::
   The default template (for the kickstart 'liveimg' command) expects an
   ``instance_info\image_info`` setting to
   be provided by the user, which serves as a base operating system image.
   In the context of the anaconda driver, it should be thought of almost
   like "stage3". If you're using a custom template, it may not be required,
   but proceed with caution.
   See `pykickstart documentation <https://pykickstart.readthedocs.io/en/latest/kickstart-docs.html#liveimg>`_
   for more information on liveimg file format, structure, and use.

.. code-block:: shell

        baremetal node set <node> \
            --instance_info ks_template=<URL>

If you do choose to use a liveimg with a customized template, or if you wish
to use the stock template with a liveimg, you will need to provide this
setting.

.. code-block:: shell

        baremetal node set <node> \
            --instance_info image_info=<URL>

.. warning::
   This is required if you do *not* utilize a customised template. As in use
   Ironic's stock template.

The pattern of deployment in this case is identical to a deployment case
where Ironic is integrated with OpenStack, however in this case Ironic
collects the files, and stages them appropriately.

At this point, you should be able to request the baremetal node to deploy.

Standalone using a repository
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Anaconda supports a concept of passing a repository as opposed to a dedicated
URL path which has a ``.treeinfo`` file, which tells the initial boot scripts
where to get various dependencies, such as what would be used as the anaconda
``stage2`` ramdisk. Unfortunately, this functionality is not well documented.

An example ``.treeinfo`` file can be found at
http://mirror.stream.centos.org/9-stream/BaseOS/x86_64/os/.treeinfo.

.. note::
   In the context of the ``.treeinfo`` file and the related folder structure
   for a deployment utilizing the ``anaconda`` deployment interface,
   ``images/install.img`` file represents a ``stage2`` ramdisk.

In the context of one wishing to deploy Centos Stream-9, the following may
be useful.

.. code-block:: shell

       baremetal node set <node> \
           --instance_info image_source=http://mirror.stream.centos.org/9-stream/BaseOS/x86_64/os/ \
           --instance_info kernel=http://mirror.stream.centos.org/9-stream/BaseOS/x86_64/os/images/pxeboot/vmlinuz \
           --instance_info ramdisk=http://mirror.stream.centos.org/9-stream/BaseOS/x86_64/os/images/pxeboot/initrd.img

Once set, a kickstart template can be provided via an ``instance_info``
parameter, and the node deployed.

Deployment Process
------------------

At a high level, the mechanics of the anaconda driver works in the following
flow, where we also note the stages and purpose of each part for informational
purposes.

#. Network Boot Program (Such as iPXE) downloads the kernel, and initial
   ramdisk.
#. Kernel launches, uncompresses initial ramdisk, and executes init inside
   of the ramdisk.
#. The initial ramdisk boot scripts, such as Dracut, recognize the kernel
   command line parameters Ironic supplied with the boot configuration,
   and downloads the second stage artifacts, in this case called the
   ``stage2`` image. This image contains Anaconda and base dependencies.
#. Anaconda downloads and parses the kickstart configuration which was
   also supplied on the kernel command line, and executes the commands
   as defined in the kickstart template.
#. The kickstart template, if specified in its contents, downloads a
   ``liveimg`` which is used as the base operating system image to
   start with.

Configuration Considerations
----------------------------

When using the ``anaconda`` deployment interface, some configuration
parameters may need to be adjusted in your environment. This is in large
part due to the general defaults being set to much lower values for image
based deployments, but the way the anaconda deployment interface works,
you may need to make some adjustments.

* ``[conductor]deploy_callback_timeout`` likely needs to be adjusted
  for most ``anaconda`` deployment interface users. By default this
  is a timer which looks for "agents" which have not checked in with
  Ironic, or agents which may have crashed or failed after they
  started. If the value is reached, then the current operation is failed.
  This value should be set to a number of seconds which exceeds your
  average anaconda deployment time.
* ``[pxe]boot_retry_timeout`` can also be triggered and result in
  an anaconda deployment in progress getting reset as it is intended
  to reboot nodes which might have failed their initial PXE operation.
  Depending on sizes of images, and the exact nature of what was deployed,
  it may be necessary to ensure this is a much higher value.

Limitations
-----------

* This deploy interface has only been tested with Red Hat based operating
  systems that use anaconda. Other systems are not supported.

* Runtime TLS certifiate injection into ramdisks is not supported. Assets
  such as ``ramdisk`` or a ``stage2`` ramdisk image need to have trusted
  Certificate Authority certificates present within the images *or* the
  Ironic API endpoint utilized should utilize a known trusted Certificate
  Authority.

* The ``anaconda`` tooling deploying the instance/workload does not
  heartbeat to Ironic like the ``ironic-python-agent`` driven ramdisks.
  As such, you may need to adjust some timers. See
  `Configuration Considerations`_ for some details on this.

.. _`anaconda`: https://fedoraproject.org/wiki/Anaconda
.. _`ks.cfg.template`: https://opendev.org/openstack/ironic/src/branch/master/ironic/drivers/modules/ks.cfg.template
