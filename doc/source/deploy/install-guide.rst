.. _install-guide:

==================
Installation Guide
==================

This document is continually updated and reflects the latest
available code of the Bare Metal service (ironic).
Users of releases may encounter differences and are encouraged
to look at earlier versions of this document for guidance.


Service overview
================

The `service overview`_ section has been moved to the Bare Metal service
Install Guide.

.. _`service overview`: http://docs.openstack.org/project-install-guide/baremetal/draft/get_started.html

Install and configure prerequisites
===================================

The `prerequisites`_ section has been moved to the Bare Metal service Install
Guide.

.. _`prerequisites`: http://docs.openstack.org/project-install-guide/baremetal/draft/install-ubuntu.html#prerequisites

Install the Bare Metal service
==============================

The `Install and configure components`_ section has been moved to the Bare
Metal service Install Guide.

.. _`Install and configure components`: http://docs.openstack.org/project-install-guide/baremetal/draft/install-ubuntu.html#install-and-configure-components


Configure the Bare Metal service
================================

The `Install and configure components`_ section has been moved to the Bare
Metal service Install Guide.

.. _`Install and configure components`: http://docs.openstack.org/project-install-guide/baremetal/draft/install-ubuntu.html#install-and-configure-components


Configure Compute to use the Bare Metal service
===============================================

The `Configure Compute to use the Bare Metal service`_ section has been moved
to the Bare Metal service Install Guide.

.. _`Configure Compute to use the Bare Metal service`: http://docs.openstack.org/project-install-guide/baremetal/draft/configure-integration.html#configure-compute-to-use-the-bare-metal-service

.. _NeutronFlatNetworking:

Configure Networking to communicate with the bare metal server
==============================================================

The `Configure Networking to communicate with the bare metal server`_ section
has been moved to the Bare Metal service Install Guide.

.. _`Configure Networking to communicate with the bare metal server`: http://docs.openstack.org/project-install-guide/baremetal/draft/configure-integration.html#configure-networking-to-communicate-with-the-bare-metal-server


Configuring Tenant Networks
===========================

See :ref:`multitenancy`

.. _CleaningNetworkSetup:

Configure the Bare Metal service for cleaning
=============================================

The `Configure the Bare Metal service for cleaning`_ section
has been moved to the Bare Metal service Install Guide.

.. _`Configure the Bare Metal service for cleaning`: http://docs.openstack.org/project-install-guide/baremetal/draft/configure-cleaning.html

.. _ImageRequirement:

Image requirements
==================

The `Image requirements`_ section has been moved to the Bare Metal service
Install Guide.

.. _`Image requirements`: http://docs.openstack.org/project-install-guide/baremetal/draft/configure-integration.html#configure-the-image-service

Flavor creation
===============

You'll need to create a special bare metal flavor in the Compute service.
The flavor is mapped to the bare metal node through the hardware specifications.

#. Change these to match your hardware::

    RAM_MB=1024
    CPU=2
    DISK_GB=100
    ARCH={i686|x86_64}

#. Create the bare metal flavor by executing the following command::

    nova flavor-create my-baremetal-flavor auto $RAM_MB $DISK_GB $CPU

   *Note: You can replace auto with your own flavor id.*

#. Set the architecture as extra_specs information of the flavor. This
   will be used to match against the properties of bare metal nodes::

    nova flavor-key my-baremetal-flavor set cpu_arch=$ARCH

#. Associate the deploy ramdisk and kernel images with the ironic node::

    ironic node-update $NODE_UUID add \
    driver_info/deploy_kernel=$DEPLOY_VMLINUZ_UUID \
    driver_info/deploy_ramdisk=$DEPLOY_INITRD_UUID


Setup the drivers for the Bare Metal service
============================================

PXE setup
---------

If you will be using PXE, it needs to be set up on the Bare Metal service
node(s) where ``ironic-conductor`` is running.

#. Make sure the tftp root directory exist and can be written to by the
   user the ``ironic-conductor`` is running as. For example::

    sudo mkdir -p /tftpboot
    sudo chown -R ironic /tftpboot

#. Install tftp server and the syslinux package with the PXE boot images::

    Ubuntu: (Up to and including 14.04)
        sudo apt-get install xinetd tftpd-hpa syslinux-common syslinux

    Ubuntu: (14.10 and after)
        sudo apt-get install xinetd tftpd-hpa syslinux-common pxelinux

    Fedora 21/RHEL7/CentOS7:
        sudo yum install tftp-server syslinux-tftpboot xinetd

    Fedora 22 or higher:
         sudo dnf install tftp-server syslinux-tftpboot xinetd

#. Using xinetd to provide a tftp server setup to serve ``/tftpboot``.
   Create or edit ``/etc/xinetd.d/tftp`` as below::

    service tftp
    {
      protocol        = udp
      port            = 69
      socket_type     = dgram
      wait            = yes
      user            = root
      server          = /usr/sbin/in.tftpd
      server_args     = -v -v -v -v -v --map-file /tftpboot/map-file /tftpboot
      disable         = no
      # This is a workaround for Fedora, where TFTP will listen only on
      # IPv6 endpoint, if IPv4 flag is not used.
      flags           = IPv4
    }

   and restart xinetd service::

    Ubuntu:
        sudo service xinetd restart

    Fedora:
        sudo systemctl restart xinetd

#. Copy the PXE image to ``/tftpboot``. The PXE image might be found at [1]_::

    Ubuntu (Up to and including 14.04):
        sudo cp /usr/lib/syslinux/pxelinux.0 /tftpboot

    Ubuntu (14.10 and after):
        sudo cp /usr/lib/PXELINUX/pxelinux.0 /tftpboot

#. If whole disk images need to be deployed via PXE-netboot, copy the
   chain.c32 image to ``/tftpboot`` to support it. The chain.c32 image
   might be found at::

    Ubuntu (Up to and including 14.04):
        sudo cp /usr/lib/syslinux/chain.c32 /tftpboot

    Ubuntu (14.10 and after):
        sudo cp /usr/lib/syslinux/modules/bios/chain.c32 /tftpboot

    Fedora/RHEL7/CentOS7:
        sudo cp /boot/extlinux/chain.c32 /tftpboot

#. If the version of syslinux is **greater than** 4 we also need to make sure
   that we copy the library modules into the ``/tftpboot`` directory [2]_
   [1]_::

    Ubuntu:
        sudo cp /usr/lib/syslinux/modules/*/ldlinux.* /tftpboot

#. Create a map file in the tftp boot directory (``/tftpboot``)::

    echo 're ^(/tftpboot/) /tftpboot/\2' > /tftpboot/map-file
    echo 're ^/tftpboot/ /tftpboot/' >> /tftpboot/map-file
    echo 're ^(^/) /tftpboot/\1' >> /tftpboot/map-file
    echo 're ^([^/]) /tftpboot/\1' >> /tftpboot/map-file

.. [1] On **Fedora/RHEL** the ``syslinux-tftpboot`` package already install
       the library modules and PXE image at ``/tftpboot``. If the TFTP server
       is configured to listen to a different directory you should copy the
       contents of ``/tftpboot`` to the configured directory
.. [2] http://www.syslinux.org/wiki/index.php/Library_modules


PXE UEFI setup
--------------

If you want to deploy on a UEFI supported bare metal, perform these additional
steps on the ironic conductor node to configure the PXE UEFI environment.

#. Install Grub2 and shim packages::

    Ubuntu: (14.04LTS and later)
        sudo apt-get install grub-efi-amd64-signed shim-signed

    Fedora 21/RHEL7/CentOS7:
        sudo yum install grub2-efi shim

    Fedora 22 or higher:
        sudo dnf install grub2-efi shim

#. Copy grub and shim boot loader images to ``/tftpboot`` directory::

    Ubuntu: (14.04LTS and later)
        sudo cp /usr/lib/shim/shim.efi.signed /tftpboot/bootx64.efi
        sudo cp /usr/lib/grub/x86_64-efi-signed/grubnetx64.efi.signed  \
        /tftpboot/grubx64.efi

    Fedora: (21 and later)
        sudo cp /boot/efi/EFI/fedora/shim.efi /tftpboot/bootx64.efi
        sudo cp /boot/efi/EFI/fedora/grubx64.efi /tftpboot/grubx64.efi

    CentOS: (7 and later)
        sudo cp /boot/efi/EFI/centos/shim.efi /tftpboot/bootx64.efi
        sudo cp /boot/efi/EFI/centos/grubx64.efi /tftpboot/grubx64.efi

#. Create master grub.cfg::

    Ubuntu: Create grub.cfg under ``/tftpboot/grub`` directory.
        GRUB_DIR=/tftpboot/grub

    Fedora: Create grub.cfg under ``/tftpboot/EFI/fedora`` directory.
         GRUB_DIR=/tftpboot/EFI/fedora

    CentOS: Create grub.cfg under ``/tftpboot/EFI/centos`` directory.
        GRUB_DIR=/tftpboot/EFI/centos

    Create directory GRUB_DIR
      sudo mkdir -p $GRUB_DIR

   This file is used to redirect grub to baremetal node specific config file.
   It redirects it to specific grub config file based on DHCP IP assigned to
   baremetal node.

   .. literalinclude:: ../../../ironic/drivers/modules/master_grub_cfg.txt

   Change the permission of grub.cfg::

    sudo chmod 644 $GRUB_DIR/grub.cfg

#. Update the bare metal node with ``boot_mode`` capability in node's properties
   field::

    ironic node-update <node-uuid> add properties/capabilities='boot_mode:uefi'

#. Make sure that bare metal node is configured to boot in UEFI boot mode and
   boot device is set to network/pxe.

   NOTE: ``pxe_ilo`` driver supports automatic setting of UEFI boot mode and
   boot device on the bare metal node. So this step is not required for
   ``pxe_ilo`` driver.

.. note::
  For more information on configuring boot modes, see boot_mode_support_.


Elilo: an alternative to Grub2
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Elilo is a UEFI bootloader. It is an alternative to Grub2, although it
isn't recommended since it is not being supported.

#. Download and untar the elilo bootloader version >= 3.16 from
   http://sourceforge.net/projects/elilo/::

    sudo tar zxvf elilo-3.16-all.tar.gz

#. Copy the elilo boot loader image to ``/tftpboot`` directory::

    sudo cp ./elilo-3.16-x86_64.efi /tftpboot/elilo.efi

#. Update bootfile and template file configuration parameters for UEFI
   PXE boot in the Bare Metal Service's configuration file
   (/etc/ironic/ironic.conf)::

    [pxe]

    # Bootfile DHCP parameter for UEFI boot mode. (string value)
    uefi_pxe_bootfile_name=elilo.efi

    # Template file for PXE configuration for UEFI boot loader.
    # (string value)
    uefi_pxe_config_template=$pybasedir/drivers/modules/elilo_efi_pxe_config.template


iPXE setup
----------

An alternative to PXE boot, iPXE was introduced in the Juno release
(2014.2.0) of Bare Metal service.

If you will be using iPXE to boot instead of PXE, iPXE needs to be set up
on the Bare Metal service node(s) where ``ironic-conductor`` is running.

#. Make sure these directories exist and can be written to by the user
   the ``ironic-conductor`` is running as. For example::

    sudo mkdir -p /tftpboot
    sudo mkdir -p /httpboot
    sudo chown -R ironic /tftpboot
    sudo chown -R ironic /httpboot

#. Create a map file in the tftp boot directory (``/tftpboot``)::

    echo 'r ^([^/]) /tftpboot/\1' > /tftpboot/map-file
    echo 'r ^(/tftpboot/) /tftpboot/\2' >> /tftpboot/map-file

#. Set up TFTP and HTTP servers.

   These servers should be running and configured to use the local
   /tftpboot and /httpboot directories respectively, as their root
   directories. (Setting up these servers is outside the scope of this
   install guide.)

   These root directories need to be mounted locally to the
   ``ironic-conductor`` services, so that the services can access them.

   The Bare Metal service's configuration file (/etc/ironic/ironic.conf)
   should be edited accordingly to specify the TFTP and HTTP root
   directories and server addresses. For example::

    [pxe]

    # Ironic compute node's tftp root path. (string value)
    tftp_root=/tftpboot

    # IP address of Ironic compute node's tftp server. (string
    # value)
    tftp_server=192.168.0.2

    [deploy]
    # Ironic compute node's http root path. (string value)
    http_root=/httpboot

    # Ironic compute node's HTTP server URL. Example:
    # http://192.1.2.3:8080 (string value)
    http_url=http://192.168.0.2:8080

#. Install the iPXE package with the boot images::

    Ubuntu:
        apt-get install ipxe

    Fedora 21/RHEL7/CentOS7:
        yum install ipxe-bootimgs

    Fedora 22 or higher:
        dnf install ipxe-bootimgs

#. Copy the iPXE boot image (``undionly.kpxe`` for **BIOS** and
   ``ipxe.efi`` for **UEFI**) to ``/tftpboot``. The binary might
   be found at::

    Ubuntu:
        cp /usr/lib/ipxe/{undionly.kpxe,ipxe.efi} /tftpboot

    Fedora/RHEL7/CentOS7:
        cp /usr/share/ipxe/{undionly.kpxe,ipxe.efi} /tftpboot

   .. note::
      If the packaged version of the iPXE boot image doesn't work, you can
      download a prebuilt one from http://boot.ipxe.org or build one image
      from source, see http://ipxe.org/download for more information.

#. Enable/Configure iPXE in the Bare Metal Service's configuration file
   (/etc/ironic/ironic.conf)::

    [pxe]

    # Enable iPXE boot. (boolean value)
    ipxe_enabled=True

    # Neutron bootfile DHCP parameter. (string value)
    pxe_bootfile_name=undionly.kpxe

    # Bootfile DHCP parameter for UEFI boot mode. (string value)
    uefi_pxe_bootfile_name=ipxe.efi

    # Template file for PXE configuration. (string value)
    pxe_config_template=$pybasedir/drivers/modules/ipxe_config.template

    # Template file for PXE configuration for UEFI boot loader.
    # (string value)
    uefi_pxe_config_template=$pybasedir/drivers/modules/ipxe_config.template

#. Restart the ``ironic-conductor`` process::

    Fedora/RHEL7/CentOS7:
      sudo systemctl restart openstack-ironic-conductor

    Ubuntu:
      sudo service ironic-conductor restart


Networking service configuration
--------------------------------

DHCP requests from iPXE need to have a DHCP tag called ``ipxe``, in order
for the DHCP server to tell the client to get the boot.ipxe script via
HTTP. Otherwise, if the tag isn't there, the DHCP server will tell the
DHCP client to chainload the iPXE image (undionly.kpxe).
The Networking service needs to be configured to create this DHCP tag,
since it isn't created by default.

#. Create a custom ``dnsmasq.conf`` file with a setting for the ipxe tag. For
   example, create the file ``/etc/dnsmasq-ironic.conf`` with the content::

    # Create the "ipxe" tag if request comes from iPXE user class
    dhcp-userclass=set:ipxe,iPXE

    # Alternatively, create the "ipxe" tag if request comes from DHCP option 175
    # dhcp-match=set:ipxe,175

#. In the Networking service DHCP Agent configuration file (typically located at
   /etc/neutron/dhcp_agent.ini), set the custom ``/etc/dnsmasq-ironic.conf``
   file as the dnsmasq configuration file::

    [DEFAULT]
    dnsmasq_config_file = /etc/dnsmasq-ironic.conf


#. Restart the ``neutron-dhcp-agent`` process::

    service neutron-dhcp-agent restart


IPMI support
------------

If using the IPMITool driver, the ``ipmitool`` command must be present on the
service node(s) where ``ironic-conductor`` is running. On most distros, this
is provided as part of the ``ipmitool`` package. Source code is available at
http://ipmitool.sourceforge.net/

Note that certain distros, notably Mac OS X and SLES, install ``openipmi``
instead of ``ipmitool`` by default. THIS DRIVER IS NOT COMPATIBLE WITH
``openipmi`` AS IT RELIES ON ERROR HANDLING OPTIONS NOT PROVIDED BY THIS TOOL.

Check that you can connect to and authenticate with the IPMI
controller in your bare metal server by using ``ipmitool``::

    ipmitool -I lanplus -H <ip-address> -U <username> -P <password> chassis power status

<ip-address> = The IP of the IPMI controller you want to access

*Note:*

#. This is not the bare metal node's main IP. The IPMI controller
   should have its own unique IP.

#. In case the above command doesn't return the power status of the
   bare metal server, check for these:

   - ``ipmitool`` is installed.
   - The IPMI controller on your bare metal server is turned on.
   - The IPMI controller credentials passed in the command are right.
   - The conductor node has a route to the IPMI controller. This can be
     checked by just pinging the IPMI controller IP from the conductor
     node.

.. note::
   If there are slow or unresponsive BMCs in the environment, the retry_timeout
   configuration option in the [ipmi] section may need to be lowered. The
   default is fairly conservative, as setting this timeout too low can cause
   older BMCs to crash and require a hard-reset.

Bare Metal service supports sending IPMI sensor data to Telemetry with pxe_ipmitool,
pxe_ipminative, agent_ipmitool, agent_pyghmi, agent_ilo, iscsi_ilo, pxe_ilo,
and with pxe_irmc driver starting from Kilo release. By default, support for
sending IPMI sensor data to Telemetry is disabled. If you want to enable it,
you should make the following two changes in ``ironic.conf``:

* ``notification_driver = messaging`` in the ``DEFAULT`` section
* ``send_sensor_data = true`` in the ``conductor`` section

If you want to customize the sensor types which will be sent to Telemetry,
change the ``send_sensor_data_types`` option. For example, the below
settings will send temperature, fan, voltage and these three sensor types
of data to Telemetry:

* send_sensor_data_types=Temperature,Fan,Voltage

If we use default value 'All' for all the sensor types which are supported by
Telemetry, they are:

* Temperature, Fan, Voltage, Current


Configure node web console
--------------------------

See :ref:`console`.

.. _boot_mode_support:

Boot mode support
-----------------

The following drivers support setting of boot mode (Legacy BIOS or UEFI).

* ``pxe_ipmitool``

The boot modes can be configured in Bare Metal service in the following way:

* When no boot mode setting is provided, these drivers default the boot_mode
  to Legacy BIOS.

* Only one boot mode (either ``uefi`` or ``bios``) can be configured for
  the node.

* If the operator wants a node to boot always in ``uefi`` mode or ``bios``
  mode, then they may use ``capabilities`` parameter within ``properties``
  field of an bare metal node.  The operator must manually set the appropriate
  boot mode on the bare metal node.

  To configure a node in ``uefi`` mode, then set ``capabilities`` as below::

    ironic node-update <node-uuid> add properties/capabilities='boot_mode:uefi'

  Nodes having ``boot_mode`` set to ``uefi`` may be requested by adding an
  ``extra_spec`` to the Compute service flavor::

    nova flavor-key ironic-test-3 set capabilities:boot_mode="uefi"
    nova boot --flavor ironic-test-3 --image test-image instance-1

  If ``capabilities`` is used in ``extra_spec`` as above, nova scheduler
  (``ComputeCapabilitiesFilter``) will match only bare metal nodes which have
  the ``boot_mode`` set appropriately in ``properties/capabilities``. It will
  filter out rest of the nodes.

  The above facility for matching in the Compute service can be used in
  heterogeneous environments where there is a mix of ``uefi`` and ``bios``
  machines, and operator wants to provide a choice to the user regarding
  boot modes. If the flavor doesn't contain ``boot_mode`` and ``boot_mode``
  is configured for bare metal nodes, then nova scheduler will consider all
  nodes and user may get either ``bios`` or ``uefi`` machine.

.. _choosing_the_disk_label:

Choosing the disk label
-----------------------

.. note::
   The term ``disk label`` is historically used in Ironic and was taken
   from `parted <https://www.gnu.org/software/parted>`_. Apparently
   everyone seems to have a different word for ``disk label`` - these
   are all the same thing: disk type, partition table, partition map
   and so on...

Ironic allows operators to choose which disk label they want their
bare metal node to be deployed with when Ironic is responsible for
partitioning the disk; therefore choosing the disk label does not apply
when the image being deployed is a ``whole disk image``.

There are some edge cases where someone may want to choose a specific
disk label for the images being deployed, including but not limited to:

* For machines in ``bios`` boot mode with disks larger than 2 terabytes
  it's recommended to use a ``gpt`` disk label. That's because
  a capacity beyond 2 terabytes is not addressable by using the
  MBR partitioning type. But, although GPT claims to be backward
  compatible with legacy BIOS systems `that's not always the case
  <http://www.rodsbooks.com/gdisk/bios.html>`_.

* Operators may want to force the partitioning to be always MBR (even
  if the machine is deployed with boot mode ``uefi``) to avoid breakage
  of applications and tools running on those instances.

The disk label can be configured in two ways; when Ironic is used with
the Compute service or in standalone mode. The following bullet points
and sections will describe both methods:

* When no disk label is provided Ironic will configure it according
  to the `boot mode <boot_mode_support_>`_; ``bios`` boot mode will use
  ``msdos`` and ``uefi`` boot mode will use ``gpt``.

* Only one disk label - either ``msdos`` or ``gpt`` - can be configured
  for the node.

When used with Compute service
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

When Ironic is used with the Compute service the disk label should be
set to node's ``properties/capabilities`` field and also to the flavor
which will request such capability, for example::

    ironic node-update <node-uuid> add properties/capabilities='disk_label:gpt'

As for the flavor::

    nova flavor-key baremetal set capabilities:disk_label="gpt"

When used in standalone mode
~~~~~~~~~~~~~~~~~~~~~~~~~~~~

When used without the Compute service, the disk label should be set
directly to the node's ``instance_info`` field, as below::

    ironic node-update <node-uuid> add instance_info/capabilities='{"disk_label": "gpt"}'


Local boot with partition images
================================

Starting with the Kilo release, Bare Metal service supports local boot with
partition images, meaning that after the deployment the node's subsequent
reboots won't happen via PXE or Virtual Media. Instead, it will boot from a
local boot loader installed on the disk.

It's important to note that in order for this to work the image being
deployed with Bare Metal service **must** contain ``grub2`` installed within it.

Enabling the local boot is different when Bare Metal service is used with
Compute service and without it.
The following sections will describe both methods.

.. note::
   The local boot feature is dependent upon a updated deploy ramdisk built
   with diskimage-builder_ **version >= 0.1.42** or ironic-python-agent_
   in the kilo-era.


Enabling local boot with Compute service
----------------------------------------

To enable local boot we need to set a capability on the bare metal node,
for example::

    ironic node-update <node-uuid> add properties/capabilities="boot_option:local"


Nodes having ``boot_option`` set to ``local`` may be requested by adding
an ``extra_spec`` to the Compute service flavor, for example::

    nova flavor-key baremetal set capabilities:boot_option="local"


.. note::
    If the node is configured to use ``UEFI``, Bare Metal service will create
    an ``EFI partition`` on the disk and switch the partition table format to
    ``gpt``. The ``EFI partition`` will be used later by the boot loader
    (which is installed from the deploy ramdisk).


Enabling local boot without Compute
-----------------------------------

Since adding ``capabilities`` to the node's properties is only used by
the nova scheduler to perform more advanced scheduling of instances,
we need a way to enable local boot when Compute is not present. To do that
we can simply specify the capability via the ``instance_info`` attribute
of the node, for example::

    ironic node-update <node-uuid> add instance_info/capabilities='{"boot_option": "local"}'


Enrollment
==========

After all the services have been properly configured, you should enroll your
hardware with the Bare Metal service, and confirm that the Compute service sees
the available hardware. The nodes will be visible to the Compute service once
they are in the ``available`` provision state.

.. note::
   After enrolling nodes with the Bare Metal service, the Compute service
   will not be immediately notified of the new resources. The Compute service's
   resource tracker syncs periodically, and so any changes made directly to the
   Bare Metal service's resources will become visible in the Compute service
   only after the next run of that periodic task.
   More information is in the `Troubleshooting`_ section below.

.. note::
   Any bare metal node that is visible to the Compute service may have a
   workload scheduled to it, if both the ``power`` and ``deploy`` interfaces
   pass the ``validate`` check.
   If you wish to exclude a node from the Compute service's scheduler, for
   instance so that you can perform maintenance on it, you can set the node to
   "maintenance" mode.
   For more information see the `Maintenance Mode`_ section below.

Enrollment process
------------------

This section describes the main steps to enroll a node and make it available
for provisioning. Some steps are shown separately for illustration purposes,
and may be combined if desired.

#. Create a node in the Bare Metal service. At a minimum, you must
   specify the driver name (for example, "pxe_ipmitool").
   This will return the node UUID along with other information
   about the node. The node's provision state will be ``available``. (The
   example assumes that the client is using the default API version.)::

    ironic node-create -d pxe_ipmitool
    +--------------+--------------------------------------+
    | Property     | Value                                |
    +--------------+--------------------------------------+
    | uuid         | dfc6189f-ad83-4261-9bda-b27258eb1987 |
    | driver_info  | {}                                   |
    | extra        | {}                                   |
    | driver       | pxe_ipmitool                         |
    | chassis_uuid |                                      |
    | properties   | {}                                   |
    | name         | None                                 |
    +--------------+--------------------------------------+

    ironic node-show dfc6189f-ad83-4261-9bda-b27258eb1987
    +------------------------+--------------------------------------+
    | Property               | Value                                |
    +------------------------+--------------------------------------+
    | target_power_state     | None                                 |
    | extra                  | {}                                   |
    | last_error             | None                                 |
    | maintenance_reason     | None                                 |
    | provision_state        | available                            |
    | uuid                   | dfc6189f-ad83-4261-9bda-b27258eb1987 |
    | console_enabled        | False                                |
    | target_provision_state | None                                 |
    | provision_updated_at   | None                                 |
    | maintenance            | False                                |
    | power_state            | None                                 |
    | driver                 | pxe_ipmitool                         |
    | properties             | {}                                   |
    | instance_uuid          | None                                 |
    | name                   | None                                 |
    | driver_info            | {}                                   |
    | ...                    | ...                                  |
    +------------------------+--------------------------------------+

   Beginning with the Kilo release a node may also be referred to by a logical
   name as well as its UUID. To utilize this new feature a name must be
   assigned to the node. This can be done when the node is created by
   adding the ``-n`` option to the ``node-create`` command or by updating an
   existing node with the ``node-update`` command. See `Logical Names`_ for
   examples.

   Beginning with the Liberty release, with API version 1.11 and above, a newly
   created node will have an initial provision state of ``enroll`` as opposed to
   ``available``. See `Enrolling a node`_ for more details.

#. Update the node ``driver_info`` so that Bare Metal service can manage the
   node. Different drivers may require different information about the node.
   You can determine this with the ``driver-properties`` command, as follows::

    ironic driver-properties pxe_ipmitool
    +----------------------+-------------------------------------------------------------------------------------------------------------+
    | Property             | Description                                                                                                 |
    +----------------------+-------------------------------------------------------------------------------------------------------------+
    | ipmi_address         | IP address or hostname of the node. Required.                                                               |
    | ipmi_password        | password. Optional.                                                                                         |
    | ipmi_username        | username; default is NULL user. Optional.                                                                   |
    | ...                  | ...                                                                                                         |
    | deploy_kernel        | UUID (from Glance) of the deployment kernel. Required.                                                      |
    | deploy_ramdisk       | UUID (from Glance) of the ramdisk that is mounted at boot time. Required.                                   |
    +----------------------+-------------------------------------------------------------------------------------------------------------+

    ironic node-update $NODE_UUID add \
    driver_info/ipmi_username=$USER \
    driver_info/ipmi_password=$PASS \
    driver_info/ipmi_address=$ADDRESS

   .. note::
      If IPMI is running on a port other than 623 (the default). The port must
      be added to ``driver_info`` by specifying the ``ipmi_port`` value.
      Example::

       ironic node-update $NODE_UUID add driver_info/ipmi_port=$PORT_NUMBER

      Note that you may also specify all ``driver_info`` parameters during
      ``node-create`` by passing the **-i** option multiple times.

#. Update the node's properties to match the bare metal flavor you created
   earlier::

    ironic node-update $NODE_UUID add \
    properties/cpus=$CPU \
    properties/memory_mb=$RAM_MB \
    properties/local_gb=$DISK_GB \
    properties/cpu_arch=$ARCH

   As above, these can also be specified at node creation by passing the **-p**
   option to ``node-create`` multiple times.

#. If you wish to perform more advanced scheduling of the instances based on
   hardware capabilities, you may add metadata to each node that will be
   exposed to the nova scheduler (see: `ComputeCapabilitiesFilter`_).  A full
   explanation of this is outside of the scope of this document. It can be done
   through the special ``capabilities`` member of node properties::

    ironic node-update $NODE_UUID add \
    properties/capabilities=key1:val1,key2:val2

#. As mentioned in the `Flavor Creation`_ section, if using the Kilo or later
   release of Bare Metal service, you should specify a deploy kernel and
   ramdisk which correspond to the node's driver, for example::

    ironic node-update $NODE_UUID add \
    driver_info/deploy_kernel=$DEPLOY_VMLINUZ_UUID \
    driver_info/deploy_ramdisk=$DEPLOY_INITRD_UUID

#. You must also inform Bare Metal service of the network interface cards which
   are part of the node by creating a port with each NIC's MAC address.
   These MAC addresses are passed to the Networking service during instance
   provisioning and used to configure the network appropriately::

    ironic port-create -n $NODE_UUID -a $MAC_ADDRESS

#. To check if Bare Metal service has the minimum information necessary for
   a node's driver to function, you may ``validate`` it::

    ironic node-validate $NODE_UUID

    +------------+--------+--------+
    | Interface  | Result | Reason |
    +------------+--------+--------+
    | console    | True   |        |
    | deploy     | True   |        |
    | management | True   |        |
    | power      | True   |        |
    +------------+--------+--------+

   If the node fails validation, each driver will return information as to why
   it failed::

    ironic node-validate $NODE_UUID

    +------------+--------+-------------------------------------------------------------------------------------------------------------------------------------+
    | Interface  | Result | Reason                                                                                                                              |
    +------------+--------+-------------------------------------------------------------------------------------------------------------------------------------+
    | console    | None   | not supported                                                                                                                       |
    | deploy     | False  | Cannot validate iSCSI deploy. Some parameters were missing in node's instance_info. Missing are: ['root_gb', 'image_source']        |
    | management | False  | Missing the following IPMI credentials in node's driver_info: ['ipmi_address'].                                                     |
    | power      | False  | Missing the following IPMI credentials in node's driver_info: ['ipmi_address'].                                                     |
    +------------+--------+-------------------------------------------------------------------------------------------------------------------------------------+

#. If using API version 1.11 or above, the node was created in the ``enroll``
   provision state. In order for the node to be available for deploying a
   workload (for example, by the Compute service), it needs to be in the
   ``available`` provision state. To do this, it must be moved into the
   ``manageable`` state and then moved into the ``available`` state. The
   `API version 1.11 and above`_ section describes the commands for this.

.. _ComputeCapabilitiesFilter: http://docs.openstack.org/developer/nova/devref/filter_scheduler.html?highlight=computecapabilitiesfilter


Enrolling a node
----------------
In the Liberty cycle, starting with API version 1.11, the Bare Metal service
added a new initial provision state of ``enroll`` to its state machine.

Existing automation tooling that use an API version lower than 1.11 are not
affected, since the initial provision state is still ``available``.
However, using API version 1.11 or above may break existing automation tooling
with respect to node creation.

The default API version used by (the most recent) python-ironicclient is 1.9.

The examples below set the API version for each command. To set the
API version for all commands, you can set the environment variable
``IRONIC_API_VERSION``.

API version 1.10 and below
~~~~~~~~~~~~~~~~~~~~~~~~~~

Below is an example of creating a node with API version 1.10. After creation,
the node will be in the ``available`` provision state.
Other API versions below 1.10 may be substituted in place of 1.10.

::

    ironic --ironic-api-version 1.10 node-create -d agent_ilo -n pre11

    +--------------+--------------------------------------+
    | Property     | Value                                |
    +--------------+--------------------------------------+
    | uuid         | cc4998a0-f726-4927-9473-0582458c6789 |
    | driver_info  | {}                                   |
    | extra        | {}                                   |
    | driver       | agent_ilo                            |
    | chassis_uuid |                                      |
    | properties   | {}                                   |
    | name         | pre11                                |
    +--------------+--------------------------------------+


    ironic --ironic-api-version 1.10 node-list

    +--------------------------------------+-------+---------------+-------------+--------------------+-------------+
    | UUID                                 | Name  | Instance UUID | Power State | Provisioning State | Maintenance |
    +--------------------------------------+-------+---------------+-------------+--------------------+-------------+
    | cc4998a0-f726-4927-9473-0582458c6789 | pre11 | None          | None        | available          | False       |
    +--------------------------------------+-------+---------------+-------------+--------------------+-------------+

API version 1.11 and above
~~~~~~~~~~~~~~~~~~~~~~~~~~

Beginning with API version 1.11, the initial provision state for newly created
nodes is ``enroll``. In the examples below, other API versions above 1.11 may be
substituted in place of 1.11.
::

    ironic --ironic-api-version 1.11 node-create -d agent_ilo -n post11

    +--------------+--------------------------------------+
    | Property     | Value                                |
    +--------------+--------------------------------------+
    | uuid         | 0eb013bb-1e4b-4f4c-94b5-2e7468242611 |
    | driver_info  | {}                                   |
    | extra        | {}                                   |
    | driver       | agent_ilo                            |
    | chassis_uuid |                                      |
    | properties   | {}                                   |
    | name         | post11                               |
    +--------------+--------------------------------------+


    ironic --ironic-api-version 1.11 node-list

    +--------------------------------------+--------+---------------+-------------+--------------------+-------------+
    | UUID                                 | Name   | Instance UUID | Power State | Provisioning State | Maintenance |
    +--------------------------------------+--------+---------------+-------------+--------------------+-------------+
    | 0eb013bb-1e4b-4f4c-94b5-2e7468242611 | post11 | None          | None        | enroll             | False       |
    +--------------------------------------+--------+---------------+-------------+--------------------+-------------+

In order for nodes to be available for deploying workloads on them, nodes
must be in the ``available`` provision state. To do this, nodes
created with API version 1.11 and above must be moved from the ``enroll`` state
to the ``manageable`` state and then to the ``available`` state.

To move a node to a different provision state, use the
``node-set-provision-state`` command.

.. note:: Since it is an asychronous call, the response for
          ``ironic node-set-provision-state`` will not indicate whether the
          transition succeeded or not. You can check the status of the
          operation via ``ironic node-show``. If it was successful,
          ``provision_state`` will be in the desired state. If it failed,
          there will be information in the node's ``last_error``.

After creating a node and before moving it from its initial provision state of
``enroll``, basic power and port information needs to be configured on the node.
The Bare Metal service needs this information because it verifies that it is
capable of controlling the node when transitioning the node from ``enroll`` to
``manageable`` state.

To move a node from ``enroll`` to ``manageable`` provision state::

    ironic --ironic-api-version 1.11 node-set-provision-state $NODE_UUID manage

    ironic node-show $NODE_UUID

    +------------------------+--------------------------------------------------------------------+
    | Property               | Value                                                              |
    +------------------------+--------------------------------------------------------------------+
    | ...                    | ...                                                                |
    | provision_state        | manageable                                                         | <- verify correct state
    | uuid                   | 0eb013bb-1e4b-4f4c-94b5-2e7468242611                               |
    | ...                    | ...                                                                |
    +------------------------+--------------------------------------------------------------------+

When a node is moved from the ``manageable`` to ``available`` provision
state, the node will go through automated cleaning if configured to do so (see
:ref:`CleaningNetworkSetup`).
To move a node from ``manageable`` to ``available`` provision state::

    ironic --ironic-api-version 1.11 node-set-provision-state $NODE_UUID provide

    ironic node-show $NODE_UUID

    +------------------------+--------------------------------------------------------------------+
    | Property               | Value                                                              |
    +------------------------+--------------------------------------------------------------------+
    | ...                    | ...                                                                |
    | provision_state        | available                                                          | < - verify correct state
    | uuid                   | 0eb013bb-1e4b-4f4c-94b5-2e7468242611                               |
    | ...                    | ...                                                                |
    +------------------------+--------------------------------------------------------------------+


For more details on the Bare Metal service's state machine, see the
`state machine <http://docs.openstack.org/developer/ironic/dev/states.html>`_
documentation.


Logical names
-------------
Beginning with the Kilo release a Node may also be referred to by a
logical name as well as its UUID. Names can be assigned either when
creating the node by adding the ``-n`` option to the ``node-create`` command or
by updating an existing node with the ``node-update`` command.

Node names must be unique, and conform to:

- rfc952_
- rfc1123_
- wiki_hostname_

The node is named 'example' in the following examples:
::

    ironic node-create -d agent_ipmitool -n example

or::

    ironic node-update $NODE_UUID add name=example


Once assigned a logical name, a node can then be referred to by name or
UUID interchangeably.
::

    ironic node-create -d agent_ipmitool -n example

    +--------------+--------------------------------------+
    | Property     | Value                                |
    +--------------+--------------------------------------+
    | uuid         | 71e01002-8662-434d-aafd-f068f69bb85e |
    | driver_info  | {}                                   |
    | extra        | {}                                   |
    | driver       | agent_ipmitool                       |
    | chassis_uuid |                                      |
    | properties   | {}                                   |
    | name         | example                              |
    +--------------+--------------------------------------+


    ironic node-show example

    +------------------------+--------------------------------------+
    | Property               | Value                                |
    +------------------------+--------------------------------------+
    | target_power_state     | None                                 |
    | extra                  | {}                                   |
    | last_error             | None                                 |
    | updated_at             | 2015-04-24T16:23:46+00:00            |
    | ...                    | ...                                  |
    | instance_info          | {}                                   |
    +------------------------+--------------------------------------+

.. _rfc952: http://tools.ietf.org/html/rfc952
.. _rfc1123: http://tools.ietf.org/html/rfc1123
.. _wiki_hostname: http://en.wikipedia.org/wiki/Hostname


Hardware Inspection
-------------------

Starting with the Kilo release, Bare Metal service supports hardware inspection
that simplifies enrolling nodes - please see :ref:`inspection` for details.

Specifying the disk for deployment
==================================

Starting with the Kilo release, Bare Metal service supports passing
hints to the deploy ramdisk about which disk it should pick for the
deployment. The list of support hints is:

* model (STRING): device identifier
* vendor (STRING): device vendor
* serial (STRING): disk serial number
* size (INT): size of the device in GiB

  .. note::
    A node's 'local_gb' property is often set to a value 1 GiB less than the
    actual disk size to account for partitioning (this is how DevStack, TripleO
    and Ironic Inspector work, to name a few). However, in this case ``size``
    should be the actual size. For example, for a 128 GiB disk ``local_gb``
    will be 127, but size hint will be 128.

* wwn (STRING): unique storage identifier
* wwn_with_extension (STRING): unique storage identifier with the vendor extension appended
* wwn_vendor_extension (STRING): unique vendor storage identifier
* rotational (BOOLEAN): whether it's a rotational device or not. This
  hint makes it easier to distinguish HDDs (rotational) and SSDs (not
  rotational) when choosing which disk Ironic should deploy the image onto.
* name (STRING): the device name, e.g /dev/md0


  .. warning::
     The root device hint name should only be used for devices with
     constant names (e.g RAID volumes). For SATA, SCSI and IDE disk
     controllers this hint is not recommended because the order in which
     the device nodes are added in Linux is arbitrary, resulting in
     devices like /dev/sda and /dev/sdb `switching around at boot time
     <https://access.redhat.com/documentation/en-US/Red_Hat_Enterprise_Linux/7/html/Storage_Administration_Guide/persistent_naming.html>`_.


To associate one or more hints with a node, update the node's properties
with a ``root_device`` key, for example::

    ironic node-update <node-uuid> add properties/root_device='{"wwn": "0x4000cca77fc4dba1"}'


That will guarantee that Bare Metal service will pick the disk device that
has the ``wwn`` equal to the specified wwn value, or fail the deployment if it
can not be found.

.. note::
    If multiple hints are specified, a device must satisfy all the hints.


.. _EnableHTTPSinSwift:

Enabling HTTPS in Swift
=======================

The drivers using virtual media use swift for storing boot images
and node configuration information (contains sensitive information for Ironic
conductor to provision bare metal hardware).  By default, HTTPS is not enabled
in swift. HTTPS is required to encrypt all communication between swift and Ironic
conductor and swift and bare metal (via virtual media).  It can be enabled in one
of the following ways:

* `Using an SSL termination proxy
  <http://docs.openstack.org/security-guide/secure-communication/tls-proxies-and-http-services.html>`_

* `Using native SSL support in swift
  <http://docs.openstack.org/developer/swift/deployment_guide.html>`_
  (recommended only for testing purpose by swift).

.. _EnableHTTPSinGlance:

Enabling HTTPS in Image service
===============================

Ironic drivers usually use Image service during node provisioning. By default,
image service does not use HTTPS, but it is required for secure communication.
It can be enabled by making the following changes to ``/etc/glance/glance-api.conf``:

#. `Configuring SSL support
   <http://docs.openstack.org/developer/glance/configuring.html#configuring-ssl-support>`_

#. Restart the glance-api service::

    Fedora/RHEL7/CentOS7:
        sudo systemctl restart openstack-glance-api

    Debian/Ubuntu:
        sudo service glance-api restart

See the `Glance <http://docs.openstack.org/developer/glance/>`_ documentation,
for more details on the Image service.

Enabling HTTPS communication between Image service and Object storage
=====================================================================

This section describes the steps needed to enable secure HTTPS communication between
Image service and Object storage when Object storage is used as the Backend.

To enable secure HTTPS communication between Image service and Object storage follow these steps:

#. :ref:`EnableHTTPSinSwift`.

#.  `Configure Swift Storage Backend
    <http://docs.openstack.org/developer/glance/configuring.html#configuring-the-swift-storage-backend>`_

#. :ref:`EnableHTTPSinGlance`

Enabling HTTPS communication between Image service and Bare Metal service
=========================================================================

This section describes the steps needed to enable secure HTTPS communication between
Image service and Bare Metal service.

To enable secure HTTPS communication between Bare Metal service and Image service follow these steps:

#. Edit ``/etc/ironic/ironic.conf``::

    [glance]
    ...
    glance_cafile=/path/to/certfile
    glance_protocol=https
    glance_api_insecure=False

   .. note::
      'glance_cafile' is a optional path to a CA certificate bundle to be used to validate the SSL certificate
      served by Image service.

#. Restart ironic-conductor service::

    Fedora/RHEL7/CentOS7:
        sudo systemctl restart openstack-ironic-conductor

    Debian/Ubuntu:
        sudo service ironic-conductor restart

Using Bare Metal service as a standalone service
================================================

Starting with the Kilo release, it's possible to use Bare Metal service without
other OpenStack services.

You should make the following changes to ``/etc/ironic/ironic.conf``:

#. To disable usage of Identity service tokens::

    [DEFAULT]
    ...
    auth_strategy=none

#. If you want to disable the Networking service, you should have your network
   pre-configured to serve DHCP and TFTP for machines that you're deploying.
   To disable it, change the following lines::

    [dhcp]
    ...
    dhcp_provider=none

   .. note::
      If you disabled the Networking service and the driver that you use is
      supported by at most one conductor, PXE boot will still work for your
      nodes without any manual config editing. This is because you know all
      the DHCP options that will be used for deployment and can set up your
      DHCP server appropriately.

      If you have multiple conductors per driver, it would be better to use
      Networking since it will do all the dynamically changing configurations
      for you.

If you don't use Image service, it's possible to provide images to Bare Metal
service via hrefs.

.. note::
   At the moment, only two types of hrefs are acceptable instead of Image
   service UUIDs: HTTP(S) hrefs (for example, "http://my.server.net/images/img")
   and file hrefs (file:///images/img).

There are however some limitations for different drivers:

* If you're using one of the drivers that use agent deploy method (namely,
  ``agent_ilo``, ``agent_ipmitool``, ``agent_pyghmi``, ``agent_ssh`` or
  ``agent_vbox``) you have to know MD5 checksum for your instance image. To
  compute it, you can use the following command::

   md5sum image.qcow2
   ed82def8730f394fb85aef8a208635f6  image.qcow2

  Apart from that, because of the way the agent deploy method works, image
  hrefs can use only HTTP(S) protocol.

* If you're using ``iscsi_ilo`` or ``agent_ilo`` driver, Object Storage service
  is required, as these drivers need to store floppy image that is used to pass
  parameters to deployment iso. For this method also only HTTP(S) hrefs are
  acceptable, as HP iLO servers cannot attach other types of hrefs as virtual
  media.

* Other drivers use PXE deploy method and there are no special requirements
  in this case.

Steps to start a deployment are pretty similar to those when using Compute:

#. To use the `ironic CLI <http://docs.openstack.org/developer/python-ironicclient/cli.html>`_,
   set up these environment variables. Since no authentication strategy is
   being used, the value can be any string for OS_AUTH_TOKEN. IRONIC_URL is
   the URL of the ironic-api process.
   For example::

    export OS_AUTH_TOKEN=fake-token
    export IRONIC_URL=http://localhost:6385/

#. Create a node in Bare Metal service. At minimum, you must specify the driver
   name (for example, "pxe_ipmitool"). You can also specify all the required
   driver parameters in one command. This will return the node UUID::

    ironic node-create -d pxe_ipmitool -i ipmi_address=ipmi.server.net \
    -i ipmi_username=user -i ipmi_password=pass \
    -i deploy_kernel=file:///images/deploy.vmlinuz \
    -i deploy_ramdisk=http://my.server.net/images/deploy.ramdisk

    +--------------+--------------------------------------------------------------------------+
    | Property     | Value                                                                    |
    +--------------+--------------------------------------------------------------------------+
    | uuid         | be94df40-b80a-4f63-b92b-e9368ee8d14c                                     |
    | driver_info  | {u'deploy_ramdisk': u'http://my.server.net/images/deploy.ramdisk',       |
    |              | u'deploy_kernel': u'file:///images/deploy.vmlinuz', u'ipmi_address':     |
    |              | u'ipmi.server.net', u'ipmi_username': u'user', u'ipmi_password':         |
    |              | u'******'}                                                               |
    | extra        | {}                                                                       |
    | driver       | pxe_ipmitool                                                             |
    | chassis_uuid |                                                                          |
    | properties   | {}                                                                       |
    +--------------+--------------------------------------------------------------------------+

   Note that here deploy_kernel and deploy_ramdisk contain links to
   images instead of Image service UUIDs.

#. As in case of Compute service, you can also provide ``capabilities`` to node
   properties, but they will be used only by Bare Metal service (for example,
   boot mode). Although you don't need to add properties like ``memory_mb``,
   ``cpus`` etc. as Bare Metal service will require UUID of a node you're
   going to deploy.

#. Then create a port to inform Bare Metal service of the network interface
   cards which are part of the node by creating a port with each NIC's MAC
   address. In this case, they're used for naming of PXE configs for a node::

    ironic port-create -n $NODE_UUID -a $MAC_ADDRESS

#. As there is no Compute service flavor and instance image is not provided with
   nova boot command, you also need to specify some fields in ``instance_info``.
   For PXE deployment, they are ``image_source``, ``kernel``, ``ramdisk``,
   ``root_gb``::

    ironic node-update $NODE_UUID add instance_info/image_source=$IMG \
    instance_info/kernel=$KERNEL instance_info/ramdisk=$RAMDISK \
    instance_info/root_gb=10

   Here $IMG, $KERNEL, $RAMDISK can also be HTTP(S) or file hrefs. For agent
   drivers, you don't need to specify kernel and ramdisk, but MD5 checksum of
   instance image is required::

    ironic node-update $NODE_UUID add instance_info/image_checksum=$MD5HASH

#. Validate that all parameters are correct::

    ironic node-validate $NODE_UUID

    +------------+--------+----------------------------------------------------------------+
    | Interface  | Result | Reason                                                         |
    +------------+--------+----------------------------------------------------------------+
    | console    | False  | Missing 'ipmi_terminal_port' parameter in node's driver_info.  |
    | deploy     | True   |                                                                |
    | management | True   |                                                                |
    | power      | True   |                                                                |
    +------------+--------+----------------------------------------------------------------+

#. Now you can start the deployment, run::

    ironic node-set-provision-state $NODE_UUID active

   You can manage provisioning by issuing this command. Valid provision states
   are ``active``, ``rebuild`` and ``deleted``.

For iLO drivers, fields that should be provided are:

* ``ilo_deploy_iso`` under ``driver_info``;

* ``ilo_boot_iso``, ``image_source``, ``root_gb`` under ``instance_info``.

.. note::
   Before Liberty release Ironic was not able to track non-Glance images'
   content changes. Starting with Liberty, it is possible to do so using image
   modification date. For example, for HTTP image, if 'Last-Modified' header
   value from response to a HEAD request to
   "http://my.server.net/images/deploy.ramdisk" is greater than cached image
   modification time, Ironic will re-download the content. For "file://"
   images, the file system modification time is used.


Other references
----------------

* `Enabling local boot without Compute`_


Enabling the configuration drive (configdrive)
==============================================

Starting with the Kilo release, the Bare Metal service supports exposing
a configuration drive image to the instances.

The configuration drive is used to store instance-specific metadata and is present to
the instance as a disk partition labeled ``config-2``. The configuration drive has
a maximum size of 64MB. One use case for using the configuration drive is to
expose a networking configuration when you do not use DHCP to assign IP
addresses to instances.

The configuration drive is usually used in conjunction with the Compute
service, but the Bare Metal service also offers a standalone way of using it.
The following sections will describe both methods.


When used with Compute service
------------------------------

To enable the configuration drive for a specific request, pass
``--config-drive true`` parameter to the ``nova boot`` command, for example::

    nova boot --config-drive true --flavor baremetal --image test-image instance-1

It's also possible to enable the configuration drive automatically on
all instances by configuring the ``OpenStack Compute service`` to always
create a configuration drive by setting the following option in the
``/etc/nova/nova.conf`` file, for example::

    [DEFAULT]
    ...

    force_config_drive=True

In some cases, you may wish to pass a user customized script when deploying an instance.
To do this, pass ``--user-data /path/to/file`` to the ``nova boot`` command.
More information can be found at `Provide user data to instances <http://docs.openstack.org/user-guide/cli_provide_user_data_to_instances.html>`_


When used standalone
--------------------

When used without the Compute service, the operator needs to create a configuration drive
and provide the file or HTTP URL to the Bare Metal service.

For the format of the configuration drive, Bare Metal service expects a
``gzipped`` and ``base64`` encoded ISO 9660 [*]_ file with a ``config-2``
label. The
`ironic client <http://docs.openstack.org/developer/python-ironicclient/>`_
can generate a configuration drive in the `expected format`_. Just pass a
directory path containing the files that will be injected into it via the
``--config-drive`` parameter of the ``node-set-provision-state`` command,
for example::

    ironic node-set-provision-state --config-drive /dir/configdrive_files $node_identifier active


Accessing the configuration drive data
--------------------------------------

When the configuration drive is enabled, the Bare Metal service will create a partition on the
instance disk and write the configuration drive image onto it. The
configuration drive must be mounted before use. This is performed
automatically by many tools, such as cloud-init and cloudbase-init. To mount
it manually on a Linux distribution that supports accessing devices by labels,
simply run the following::

    mkdir -p /mnt/config
    mount /dev/disk/by-label/config-2 /mnt/config


If the guest OS doesn't support accessing devices by labels, you can use
other tools such as ``blkid`` to identify which device corresponds to
the configuration drive and mount it, for example::

    CONFIG_DEV=$(blkid -t LABEL="config-2" -odevice)
    mkdir -p /mnt/config
    mount $CONFIG_DEV /mnt/config


.. [*] A config drive could also be a data block with a VFAT filesystem
       on it instead of ISO 9660. But it's unlikely that it would be needed
       since ISO 9660 is widely supported across operating systems.


Cloud-init integration
----------------------

The configuration drive can be
especially useful when used with `cloud-init
<http://cloudinit.readthedocs.org/en/latest/topics/datasources.html#config-drive>`_,
but in order to use it we should follow some rules:

* ``Cloud-init`` data should be organized in the `expected format`_.


* Since the Bare Metal service uses a disk partition as the configuration drive,
  it will only work with
  `cloud-init version >= 0.7.5 <http://bazaar.launchpad.net/~cloud-init-dev/cloud-init/trunk/view/head:/ChangeLog>`_.


* ``Cloud-init`` has a collection of data source modules, so when
  building the image with `disk-image-builder`_ we have to define
  ``DIB_CLOUD_INIT_DATASOURCES`` environment variable and set the
  appropriate sources to enable the configuration drive, for example::

    DIB_CLOUD_INIT_DATASOURCES="ConfigDrive, OpenStack" disk-image-create -o fedora-cloud-image fedora baremetal

  For more information see `how to configure cloud-init data sources
  <http://docs.openstack.org/developer/diskimage-builder/elements/cloud-init-datasources/README.html>`_.

.. _`expected format`: http://docs.openstack.org/user-guide/cli_config_drive.html#openstack-metadata-format


Appending kernel parameters to boot instances
=============================================

The Bare Metal service supports passing custom kernel parameters to boot instances to fit
users' requirements. The way to append the kernel parameters is depending on how to boot instances.

Network boot
------------
Currently, the Bare Metal service supports assigning unified kernel parameters to PXE
booted instances by:

* Modifying the ``[pxe]/pxe_append_params`` configuration option, for example::

    [pxe]

    pxe_append_params = quiet splash

* Copying a template from shipped templates to another place, for example::

    https://git.openstack.org/cgit/openstack/ironic/tree/ironic/drivers/modules/pxe_config.template

  Making the modifications and pointing to the custom template via the configuration
  options: ``[pxe]/pxe_config_template`` and ``[pxe]/uefi_pxe_config_template``.

Local boot
----------
For local boot instances, users can make use of configuration drive
(see `Enabling the configuration drive (configdrive)`_) to pass a custom
script to append kernel parameters when creating an instance. This is more
flexible and can vary per instance.
Here is an example for grub2 with ubuntu, users can customize it
to fit their use case:

    .. code:: python

     #!/usr/bin/env python
     import os

     # Default grub2 config file in Ubuntu
     grub_file = '/etc/default/grub'
     # Add parameters here to pass to instance.
     kernel_parameters = ['quiet', 'splash']
     grub_cmd = 'GRUB_CMDLINE_LINUX'
     old_grub_file = grub_file+'~'
     os.rename(grub_file, old_grub_file)
     cmdline_existed = False
     with open(grub_file, 'w') as writer, \
            open(old_grub_file, 'r') as reader:
            for line in reader:
                key = line.split('=')[0]
                if key == grub_cmd:
                    #If there is already some value:
                    if line.strip()[-1] == '"':
                        line = line.strip()[:-1] + ' ' + ' '.join(kernel_parameters) + '"'
                    cmdline_existed = True
                writer.write(line)
            if not cmdline_existed:
                line = grub_cmd + '=' + '"' + ' '.join(kernel_parameters) + '"'
                writer.write(line)

     os.remove(old_grub_file)
     os.system('update-grub')
     os.system('reboot')


.. _BuildingDeployRamdisk:

Building or downloading a deploy ramdisk image
==============================================

Ironic depends on having an image with the ironic-python-agent_ (IPA)
service running on it for controlling and deploying bare metal nodes.

You can download a pre-built version of the deploy ramdisk built with
the `CoreOS tools`_ at:

* `CoreOS deploy kernel <http://tarballs.openstack.org/ironic-python-agent/coreos/files/coreos_production_pxe.vmlinuz>`_
* `CoreOS deploy ramdisk <http://tarballs.openstack.org/ironic-python-agent/coreos/files/coreos_production_pxe_image-oem.cpio.gz>`_

Building from source
--------------------

There are two known methods for creating the deployment image with the
IPA service:

.. _BuildingCoreOSDeployRamdisk:

CoreOS tools
~~~~~~~~~~~~

#. Clone the ironic-python-agent_ project::

    git clone https://git.openstack.org/openstack/ironic-python-agent

#. Install the requirements::

    Fedora 21/RHEL7/CentOS7:
        sudo yum install docker gzip util-linux cpio findutils grep gpg

    Fedora 22 or higher:
        sudo dnf install docker gzip util-linux cpio findutils grep gpg

    Ubuntu 14.04 (trusty) or higher:
        sudo apt-get install docker.io gzip uuid-runtime cpio findutils grep gnupg

#. Change directory to ``imagebuild/coreos``::

    cd ironic-python-agent/imagebuild/coreos

#. Start the docker daemon::

    Fedora/RHEL7/CentOS7:
        sudo systemctl start docker

    Ubuntu:
        sudo service docker start

#. Create the image::

    sudo make

#. Or, create an ISO image to boot with virtual media::

    sudo make iso


.. note::
   Once built the deploy ramdisk and kernel will appear inside of a
   directory called ``UPLOAD``.


.. _BuildingDibBasedDeployRamdisk:

disk-image-builder
~~~~~~~~~~~~~~~~~~

#. Install disk-image-builder_ from pip or from your distro's packages::

    sudo pip install diskimage-builder

#. Create the image::

    disk-image-create ironic-agent fedora -o ironic-deploy

   The above command creates the deploy ramdisk and kernel named
   ``ironic-deploy.vmlinuz`` and ``ironic-deploy.initramfs`` in your
   current directory.

#. Or, create an ISO image to boot with virtual media::

    disk-image-create ironic-agent fedora iso -o ironic-deploy

   The above command creates the deploy ISO named ``ironic-deploy.iso``
   in your current directory.

.. note::
   Fedora was used as an example for the base operational system. Please
   check the `diskimage-builder documentation`_ for other supported
   operational systems.

.. _`diskimage-builder documentation`: http://docs.openstack.org/developer/diskimage-builder


Trusted boot with partition image
=================================
Starting with the Liberty release, Ironic supports trusted boot with partition
image. This means at the end of the deployment process, when the node is
rebooted with the new user image, ``trusted boot`` will be performed. It will
measure the node's BIOS, boot loader, Option ROM and the Kernel/Ramdisk, to
determine whether a bare metal node deployed by Ironic should be trusted.

It's important to note that in order for this to work the node being deployed
**must** have Intel `TXT`_ hardware support. The image being deployed with
Ironic must have ``oat-client`` installed within it.

The following will describe how to enable ``trusted boot`` and boot
with PXE and Nova:

#. Create a customized user image with ``oat-client`` installed::

    disk-image-create -u fedora baremetal oat-client -o $TRUST_IMG

   For more information on creating customized images, see `ImageRequirement`_.

#. Enable VT-x, VT-d, TXT and TPM on the node. This can be done manually through
   the BIOS. Depending on the platform, several reboots may be needed.

#. Enroll the node and update the node capability value::

    ironic node-create -d pxe_ipmitool

    ironic node-update $NODE_UUID add properties/capabilities={'trusted_boot':true}

#. Create a special flavor::

    nova flavor-key $TRUST_FLAVOR_UUID set 'capabilities:trusted_boot'=true

#. Prepare `tboot`_ and mboot.c32 and put them into tftp_root or http_root
   directory on all nodes with the ironic-conductor processes::

    Ubuntu:
        cp /usr/lib/syslinux/mboot.c32 /tftpboot/

    Fedora:
        cp /usr/share/syslinux/mboot.c32 /tftpboot/

   *Note: The actual location of mboot.c32 varies among different distribution versions.*

   tboot can be downloaded from
   https://sourceforge.net/projects/tboot/files/latest/download

#. Install an OAT Server. An `OAT Server`_ should be running and configured correctly.

#. Boot an instance with Nova::

    nova boot --flavor $TRUST_FLAVOR_UUID --image $TRUST_IMG --user-data $TRUST_SCRIPT trusted_instance

   *Note* that the node will be measured during ``trusted boot`` and the hash values saved
   into `TPM`_. An example of TRUST_SCRIPT can be found in `trust script example`_.

#. Verify the result via OAT Server.

   This is outside the scope of Ironic. At the moment, users can manually verify the result
   by following the `manual verify steps`_.

.. _`TXT`: http://en.wikipedia.org/wiki/Trusted_Execution_Technology
.. _`tboot`: https://sourceforge.net/projects/tboot
.. _`TPM`: http://en.wikipedia.org/wiki/Trusted_Platform_Module
.. _`OAT Server`: https://github.com/OpenAttestation/OpenAttestation/wiki
.. _`trust script example`: https://wiki.openstack.org/wiki/Bare-metal-trust#Trust_Script_Example
.. _`manual verify steps`: https://wiki.openstack.org/wiki/Bare-metal-trust#Manual_verify_result



Troubleshooting
===============

Once all the services are running and configured properly, and a node has been
enrolled with the Bare Metal service and is in the ``available`` provision
state, the Compute service should detect the node
as an available resource and expose it to the scheduler.

.. note::
   There is a delay, and it may take up to a minute (one periodic task cycle)
   for the Compute service to recognize any changes in the Bare Metal service's
   resources (both additions and deletions).

In addition to watching ``nova-compute`` log files, you can see the available
resources by looking at the list of Compute hypervisors. The resources reported
therein should match the bare metal node properties, and the Compute service flavor.

Here is an example set of commands to compare the resources in Compute
service and Bare Metal service::

    $ ironic node-list
    +--------------------------------------+---------------+-------------+--------------------+-------------+
    | UUID                                 | Instance UUID | Power State | Provisioning State | Maintenance |
    +--------------------------------------+---------------+-------------+--------------------+-------------+
    | 86a2b1bb-8b29-4964-a817-f90031debddb | None          | power off   | available          | False       |
    +--------------------------------------+---------------+-------------+--------------------+-------------+

    $ ironic node-show 86a2b1bb-8b29-4964-a817-f90031debddb
    +------------------------+----------------------------------------------------------------------+
    | Property               | Value                                                                |
    +------------------------+----------------------------------------------------------------------+
    | instance_uuid          | None                                                                 |
    | properties             | {u'memory_mb': u'1024', u'cpu_arch': u'x86_64', u'local_gb': u'10',  |
    |                        | u'cpus': u'1'}                                                       |
    | maintenance            | False                                                                |
    | driver_info            | { [SNIP] }                                                           |
    | extra                  | {}                                                                   |
    | last_error             | None                                                                 |
    | created_at             | 2014-11-20T23:57:03+00:00                                            |
    | target_provision_state | None                                                                 |
    | driver                 | pxe_ipmitool                                                         |
    | updated_at             | 2014-11-21T00:47:34+00:00                                            |
    | instance_info          | {}                                                                   |
    | chassis_uuid           | 7b49bbc5-2eb7-4269-b6ea-3f1a51448a59                                 |
    | provision_state        | available                                                            |
    | reservation            | None                                                                 |
    | power_state            | power off                                                            |
    | console_enabled        | False                                                                |
    | uuid                   | 86a2b1bb-8b29-4964-a817-f90031debddb                                 |
    +------------------------+----------------------------------------------------------------------+

    $ nova hypervisor-show 1
    +-------------------------+--------------------------------------+
    | Property                | Value                                |
    +-------------------------+--------------------------------------+
    | cpu_info                | baremetal cpu                        |
    | current_workload        | 0                                    |
    | disk_available_least    | -                                    |
    | free_disk_gb            | 10                                   |
    | free_ram_mb             | 1024                                 |
    | host_ip                 | [ SNIP ]                             |
    | hypervisor_hostname     | 86a2b1bb-8b29-4964-a817-f90031debddb |
    | hypervisor_type         | ironic                               |
    | hypervisor_version      | 1                                    |
    | id                      | 1                                    |
    | local_gb                | 10                                   |
    | local_gb_used           | 0                                    |
    | memory_mb               | 1024                                 |
    | memory_mb_used          | 0                                    |
    | running_vms             | 0                                    |
    | service_disabled_reason | -                                    |
    | service_host            | my-test-host                         |
    | service_id              | 6                                    |
    | state                   | up                                   |
    | status                  | enabled                              |
    | vcpus                   | 1                                    |
    | vcpus_used              | 0                                    |
    +-------------------------+--------------------------------------+


Maintenance mode
----------------
Maintenance mode may be used if you need to take a node out of the resource
pool. Putting a node in maintenance mode will prevent Bare Metal service from
executing periodic tasks associated with the node. This will also prevent
Compute service from placing a tenant instance on the node by not exposing
the node to the nova scheduler. Nodes can be placed into maintenance mode
with the following command.
::

    $ ironic node-set-maintenance $NODE_UUID on

As of the Kilo release, a maintenance reason may be included with the optional
``--reason`` command line option. This is a free form text field that will be
displayed in the ``maintenance_reason`` section of the ``node-show`` command.
::

    $ ironic node-set-maintenance $UUID on --reason "Need to add ram."

    $ ironic node-show $UUID

    +------------------------+--------------------------------------+
    | Property               | Value                                |
    +------------------------+--------------------------------------+
    | target_power_state     | None                                 |
    | extra                  | {}                                   |
    | last_error             | None                                 |
    | updated_at             | 2015-04-27T15:43:58+00:00            |
    | maintenance_reason     | Need to add ram.                     |
    | ...                    | ...                                  |
    | maintenance            | True                                 |
    | ...                    | ...                                  |
    +------------------------+--------------------------------------+

To remove maintenance mode and clear any ``maintenance_reason`` use the
following command.
::

    $ ironic node-set-maintenance $NODE_UUID off


.. _ironic-python-agent: http://docs.openstack.org/developer/ironic-python-agent/
.. _diskimage-builder: http://docs.openstack.org/developer/diskimage-builder/
