.. _ilo:

===========
iLO drivers
===========

Overview
========
iLO drivers enable to take advantage of features of iLO management engine in
HP Proliant servers.  iLO drivers are targetted for HP Proliant Gen 8 systems
and above which have iLO 4 management engine. [1]_

For more detailed and up-to-date information (like tested platforms, known
issues, etc), please check the iLO driver wiki page [6]_.

Currently there are 3 iLO drivers:

* ``iscsi_ilo``
* ``agent_ilo``
* ``pxe_ilo``.

The ``iscsi_ilo`` and ``agent_ilo`` drivers provide security enhanced
PXE-less deployment by using iLO virtual media to boot up the baremetal node.
These drivers send management info through management channel and separates
it from data channel which is used for deployment.  ``iscsi_ilo`` driver uses
deployment ramdisk built from ``diskimage-builder``, deploys from Ironic
conductor node and always does net-boot. ``agent_ilo`` driver uses deployment
ramdisk built from IPA, deploys from baremetal node and always does local boot.

``pxe_ilo`` driver uses PXE/iSCSI for deployment (just like normal PXE driver),
but support automatic setting of requested boot mode from nova. This driver
doesn't require iLO Advanced license.



Prerequisites
=============

* ``proliantutils`` is a python package which contains a set of modules for
  managing HP Proliant hardware.

  Install ``proliantutils`` [2]_ module on the Ironic conductor node. Minimum
  version required is 0.1.0.::

   $ pip install "proliantutils>=0.1.0"

* ``ipmitool`` command must be present on the service node(s) where
  ``ironic-conductor`` is running. On most distros, this is provided as part
  of the ``ipmitool`` package. Source code is available at
  http://ipmitool.sourceforge.net/.


Drivers
=======

iscsi_ilo driver
^^^^^^^^^^^^^^^^

Overview
~~~~~~~~
``iscsi_ilo`` driver was introduced as an alternative to ``pxe_ipmitool``
and ``pxe_ipminative`` drivers for HP Proliant servers. ``iscsi_ilo`` uses
virtual media feature in iLO to boot up the baremetal node instead of using
PXE or iPXE.

Target Users
~~~~~~~~~~~~

* Users who do not want to use PXE/TFTP protocol on their data centres.
* Current PXE driver passes authentication token in clear-text over
  tftp to the baremetal node. ``iscsi_ilo`` driver enhances the security
  by passing keystone authtoken and management info over encrypted
  management network. This driver may be used by users who have concerns
  on PXE drivers security issues and want to have a security enhanced
  PXE-less deployment mechanism.

Tested Platforms
~~~~~~~~~~~~~~~~
This driver should work on HP Proliant Gen8 Servers and above with iLO 4.
It has been tested with the following servers:

* ProLiant DL380e Gen8
* ProLiant DL380e Gen8
* ProLiant DL580 Gen8 UEFI
* ProLiant DL180 Gen9 UEFI

For more up-to-date information on server platform support info, refer
iLO driver wiki [6]_.

Features
~~~~~~~~
* PXE-less deploy with Virtual Media.
* Automatic detection of current boot mode.
* Automatic setting of the required boot mode if UEFI boot mode is requested
  by the nova flavor's extra spec.
* Always boot from network using Virtual Media.
* UEFI Boot Support
* Passing authentication token via secure, encrypted management network
  (Virtual Media). Provisioning is done using iSCSI over data network
  (like PXE driver), so this driver has the  benefit of security
  enhancement with the same performance. Hence it segregates management info
  from data channel.
* Remote Console
* HW Sensors
* Works well for machines with resource constraints (lesser amount of memory).

Requirements
~~~~~~~~~~~~
* **iLO 4 Advanced License** needs to be installed on iLO to enable Virtual
  Media feature.
* **Swift Object Storage Service** - iLO driver uses Swift to store temporary
  FAT images as well as boot ISO images.
* **Glance Image Service with Swift configured as its backend** - When using
  ``iscsi_ilo`` driver, the image containing the deploy ramdisk is retrieved
  from Swift directly by the iLO.


Deploy Process
~~~~~~~~~~~~~~
* Admin configures the Proliant baremetal node for iscsi_ilo driver. The
  Ironic node configured will have the ``ilo_deploy_iso`` property in its
  ``driver_info``.  This will contain the Glance UUID of the ISO
  deploy ramdisk image.
* Ironic gets a request to deploy a Glance image on the baremetal node.
* ``iscsi_ilo`` driver powers off the baremetal node.
* The driver generates a swift-temp-url for the deploy ramdisk image
  and attaches it as Virtual Media CDROM on the iLO.
* The driver creates a small FAT32 image containing parameters to
  the deploy ramdisk. This image is uploaded to Swift and its swift-temp-url
  is attached as Virtual Media Floppy on the iLO.
* The driver sets the node to boot one-time from CDROM.
* The driver powers on the baremetal node.
* The deploy kernel/ramdisk is booted on the baremetal node.  The ramdisk
  exposes the local disk over iSCSI and requests Ironic conductor to complete
  the deployment.
* The driver on the Ironic conductor writes the glance image to the
  baremetal node's disk.
* The driver bundles the boot kernel/ramdisk for the Glance deploy
  image into an ISO and then uploads it to Swift. This ISO image will be used
  for booting the deployed instance.
* The driver reboots the node.
* On the first and subsequent reboots ``iscsi_ilo`` driver attaches this boot
  ISO image in Swift as Virtual Media CDROM and then sets iLO to boot from it.

Configuring and Enabling the driver
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
1. Prepare an ISO deploy ramdisk image from ``diskimage-builder`` [3]_.  This
   can be done by adding the ``iso`` element to the ``ramdisk-image-create``
   command.  This command creates the deploy kernel/ramdisk as well as a
   bootable ISO image containing the deploy kernel and ramdisk.

   The below command creates files named ``deploy-ramdisk.kernel``,
   ``deploy-ramdisk.initramfs`` and ``deploy-ramdisk.iso`` in the current
   working directory.::

    cd <path-to-diskimage-builder>
    ./bin/ramdisk-image-create -o deploy-ramdisk ubuntu deploy-ironic iso

2. Upload this image to Glance.::

    glance image-create --name deploy-ramdisk.iso --disk-format iso --container-format bare < deploy-ramdisk.iso

3. Configure Glance image service with its storage backend as Swift. See
   [4]_ for configuration instructions.

4. Set a temp-url key for Glance user in Swift. For example, if you have
   configured Glance with user ``glance-swift`` and tenant as ``service``,
   then run the below command::

    swift --os-username=service:glance-swift post -m temp-url-key:mysecretkeyforglance

5. Fill the required parameters in the ``[glance]`` section   in
   ``/etc/ironic/ironic.conf``. Normally you would be required to fill in the
   following details.::

    [glance]
    swift_temp_url_key=mysecretkeyforglance
    swift_endpoint_url=http://10.10.1.10:8080
    swift_api_version=v1
    swift_account=AUTH_51ea2fb400c34c9eb005ca945c0dc9e1
    swift_container=glance

  The details can be retrieved by running the below command:::

   $ swift --os-username=service:glance-swift stat -v | grep -i url
   StorageURL:     http://10.10.1.10:8080/v1/AUTH_51ea2fb400c34c9eb005ca945c0dc9e1
   Meta Temp-Url-Key: mysecretkeyforglance


6. Swift must be accessible with the same admin credentials configured in
   Ironic. For example, if Ironic is configured with the below credentials in
   ``/etc/ironic/ironic.conf``.::

    [keystone_authtoken]
    admin_password = password
    admin_user = ironic
    admin_tenant_name = service

   Ensure ``auth_version`` in ``keystone_authtoken`` to 2.

   Then, the below command should work.::

    $ swift --os-username ironic --os-password password --os-tenant-name service --auth-version 2 stat
                         Account: AUTH_22af34365a104e4689c46400297f00cb
                      Containers: 2
                         Objects: 18
                           Bytes: 1728346241
    Objects in policy "policy-0": 18
      Bytes in policy "policy-0": 1728346241
               Meta Temp-Url-Key: mysecretkeyforglance
                     X-Timestamp: 1409763763.84427
                      X-Trans-Id: tx51de96a28f27401eb2833-005433924b
                    Content-Type: text/plain; charset=utf-8
                   Accept-Ranges: bytes


7. Add ``iscsi_ilo`` to the list of ``enabled_drivers`` in
   ``/etc/ironic/ironic.conf``.  For example:::

    enabled_drivers = fake,pxe_ssh,pxe_ipmitool,iscsi_ilo

8. Restart the Ironic conductor service.::

    $ service ironic-conductor restart

Registering Proliant node in Ironic
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Nodes configured for iLO driver should have the ``driver`` property set to
``iscsi_ilo``.  The following configuration values are also required in
``driver_info``:

- ``ilo_address``: IP address or hostname of the iLO.
- ``ilo_username``: Username for the iLO with administrator privileges.
- ``ilo_password``: Password for the above iLO user.
- ``ilo_deploy_iso``: The Glance UUID of the deploy ramdisk ISO image.
- ``client_port``: (optional) Port to be used for iLO operations if you are
  using a custom port on the iLO.  Default port used is 443.
- ``client_timeout``: (optional) Timeout for iLO operations. Default timeout
  is 60 seconds.
- ``console_port``: (optional) Node's UDP port for console access. Any unused
  port on the Ironic conductor node may be used.

For example, you could run a similar command like below to enroll the Proliant
node::

  ironic node-create -d iscsi_ilo -i ilo_address=<ilo-ip-address> -i ilo_username=<ilo-username> -i ilo_password=<ilo-password> -i ilo_deploy_iso=<glance-uuid-of-deploy-iso>

Boot modes
~~~~~~~~~~
Refer boot_mode_support_ for more information.

agent_ilo driver
^^^^^^^^^^^^^^^^

Overview
~~~~~~~~
``agent_ilo`` driver was introduced as an alternative to ``agent_ipmitool``
and ``agent_ipminative`` drivers for HP Proliant servers. ``agent_ilo`` driver
uses virtual media feature in HP Proliant baremetal servers to boot up the
Ironic Python Agent (IPA) on the baremetal node instead of using PXE. For
more information on IPA, refer
https://wiki.openstack.org/wiki/Ironic-python-agent.

Target Users
~~~~~~~~~~~~
* Users who do not want to use PXE/TFTP protocol on their data centres.

Tested Platforms
~~~~~~~~~~~~~~~~
This driver should work on HP Proliant Gen8 Servers and above with iLO 4.
It has been tested with the following servers:

* ProLiant DL380e Gen8
* ProLiant DL380e Gen8

This driver supports only Gen 8 Class 0 systems (BIOS only).  For
more up-to-date information, check the iLO driver wiki [6]_.

Features
~~~~~~~~
* PXE-less deploy with Virtual Media using Ironic Python Agent.
* Remote Console
* HW Sensors
* IPA runs on the baremetal node and pulls the image directly from Swift.
* IPA deployed instances always boots from local disk.
* Segregates management info from data channel.

Requirements
~~~~~~~~~~~~
* **iLO 4 Advanced License** needs to be installed on iLO to enable Virtual
  Media feature.
* **Swift Object Storage Service** - iLO driver uses Swift to store temporary
  FAT images as well as boot ISO images.
* **Glance Image Service with Swift configured as its backend** - When using
  ``agent_ilo`` driver, the image containing the agent is retrieved from
  Swift directly by the iLO.

Deploy Process
~~~~~~~~~~~~~~
* Admin configures the Proliant baremetal node for ``agent_ilo`` driver. The
  Ironic node configured will have the ``ilo_deploy_iso`` property in its
  ``driver_info``.  This will contain the Glance UUID of the ISO deploy agent
  image containing the agent.
* Ironic gets a request to deploy a Glance image on the baremetal node.
* Driver powers off the baremetal node.
* Driver generates a swift-temp-url for the deploy agent image
  and attaches it as Virtual Media CDROM on the iLO.
* Driver creates a small FAT32 image containing parameters to
  the agent ramdisk. This image is uploaded to Swift and its swift-temp-url
  is attached as Virtual Media Floppy on the iLO.
* Driver sets the node to boot one-time from CDROM.
* Driver powers on the baremetal node.
* The deploy kernel/ramdisk containing the agent is booted on the baremetal
  node.  The agent ramdisk talks to the Ironic conductor, downloads the image
  directly from Swift and writes the node's disk.
* Driver sets the node to permanently boot from disk and then reboots
  the node.

Configuring and Enabling the driver
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
1. Prepare an ISO deploy Ironic Python Agent image containing the agent [5]_.
   This can be done by using the iso-image-create script found within
   the agent. The below set of commands will create a file ``ipa-ramdisk.iso``
   in the below directory ``UPLOAD``::

    $ cd <directory-containing-ironic-python-agent>
    $ cd ./imagebuild/coreos
    $ make iso
    $ cd UPLOAD
    $ ls
    $ coreos_production_pxe_image-oem.cpio.gz  coreos_production_pxe.vmlinuz  ipa-coreos.iso


2. Upload the IPA ramdisk image to Glance.::

    glance image-create --name ipa-ramdisk.iso --disk-format iso --container-format bare < ipa-coreos.iso

3. Configure Glance image service with its storage backend as Swift. See
   [4]_ for configuration instructions.
4. Set a temp-url key for Glance user in Swift. For example, if you have
   configured Glance with user ``glance-swift`` and tenant as ``service``,
   then run the below command::

    swift --os-username=service:glance-swift post -m temp-url-key:mysecretkeyforglance

5. Fill the required parameters in the ``[glance]`` section   in
   ``/etc/ironic/ironic.conf``. Normally you would be required to fill in the
   following details.::

    [glance]
    swift_temp_url_key=mysecretkeyforglance
    swift_endpoint_url=http://10.10.1.10:8080
    swift_api_version=v1
    swift_account=AUTH_51ea2fb400c34c9eb005ca945c0dc9e1
    swift_container=glance

  The details can be retrieved by running the below command:::

   $ swift --os-username=service:glance-swift stat -v | grep -i url
   StorageURL:     http://10.10.1.10:8080/v1/AUTH_51ea2fb400c34c9eb005ca945c0dc9e1
   Meta Temp-Url-Key: mysecretkeyforglance


6. Swift must be accessible with the same admin credentials configured in
   Ironic. For example, if Ironic is configured with the below credentials in
   ``/etc/ironic/ironic.conf``.::

    [keystone_authtoken]
    admin_password = password
    admin_user = ironic
    admin_tenant_name = service

   Ensure ``auth_version`` in ``keystone_authtoken`` to 2.

   Then, the below command should work.::

    $ swift --os-username ironic --os-password password --os-tenant-name service --auth-version 2 stat
                         Account: AUTH_22af34365a104e4689c46400297f00cb
                      Containers: 2
                         Objects: 18
                           Bytes: 1728346241
    Objects in policy "policy-0": 18
      Bytes in policy "policy-0": 1728346241
               Meta Temp-Url-Key: mysecretkeyforglance
                     X-Timestamp: 1409763763.84427
                      X-Trans-Id: tx51de96a28f27401eb2833-005433924b
                    Content-Type: text/plain; charset=utf-8
                   Accept-Ranges: bytes


7. Add ``agent_ilo`` to the list of ``enabled_drivers`` in
   ``/etc/ironic/ironic.conf``.  For example:::

    enabled_drivers = fake,pxe_ssh,pxe_ipmitool,agent_ilo

8. Restart the Ironic conductor service.::

    $ service ironic-conductor restart


Registering Proliant node in Ironic
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Nodes configured for iLO driver should have the ``driver`` property set to
``agent_ilo``.  The following configuration values are also required in
``driver_info``:

- ``ilo_address``: IP address or hostname of the iLO.
- ``ilo_username``: Username for the iLO with administrator privileges.
- ``ilo_password``: Password for the above iLO user.
- ``ilo_deploy_iso``: The Glance UUID of the deploy agent ISO image containing
   the agent.
- ``client_port``: (optional) Port to be used for iLO operations if you are
  using a custom port on the iLO. Default port used is 443.
- ``client_timeout``: (optional) Timeout for iLO operations. Default timeout
  is 60 seconds.
- ``console_port``: (optional) Node's UDP port for console access. Any unused
  port on the Ironic conductor node may be used.

For example, you could run a similar command like below to enroll the Proliant
node::

  ironic node-create -d agent_ilo -i ilo_address=<ilo-ip-address> -i ilo_username=<ilo-username> -i ilo_password=<ilo-password> -i ilo_deploy_iso=<glance-uuid-of-deploy-iso>

pxe_ilo driver
^^^^^^^^^^^^^^

Overview
~~~~~~~~
``pxe_ilo`` driver uses PXE/iSCSI (just like ``pxe_ipmitool`` driver) to
deploy the image and uses iLO to do all management operations on the baremetal
node(instead of using IPMI).

Target Users
~~~~~~~~~~~~
* Users who want to use PXE/iSCSI for deployment in their environment or who
  don't have Advanced License in their iLO.
* Users who don't want to configure boot mode manually on the baremetal node.

Tested Platforms
~~~~~~~~~~~~~~~~
This driver should work on HP Proliant Gen8 Servers and above with iLO 4.
It has been tested with the following servers:

* ProLiant DL380e Gen8
* ProLiant DL380e Gen8
* ProLiant DL580 Gen8 (BIOS/UEFI)

The driver doesn't work on BIOS mode on DL580 Gen8 and Gen9 systems due to
an issue in the firmware.  For information on this, refer iLO driver
wiki [6]_.

For more up-to-date information, check the iLO driver wiki [6]_.

Features
~~~~~~~~
* Automatic detection of current boot mode.
* Automatic setting of the required boot mode if UEFI boot mode is requested
  by the nova flavor's extra spec.

Requirements
~~~~~~~~~~~~
None.

Configuring and Enabling the driver
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
1. Prepare an ISO deploy ramdisk image from ``diskimage-builder`` [3]_.

   The below command creates a file named ``deploy-ramdisk.kernel`` and
   ``deploy-ramdisk.initramfs`` in the current working directory::

    cd <path-to-diskimage-builder>
    ./bin/ramdisk-image-create -o deploy-ramdisk ubuntu deploy-ironic

2. Upload this image to Glance.::

    glance image-create --name deploy-ramdisk.kernel --disk-format aki --container-format aki < deploy-ramdisk.kernel
    glance image-create --name deploy-ramdisk.initramfs --disk-format ari --container-format ari < deploy-ramdisk.initramfs

7. Add ``pxe_ilo`` to the list of ``enabled_drivers`` in
   ``/etc/ironic/ironic.conf``.  For example:::

    enabled_drivers = fake,pxe_ssh,pxe_ipmitool,pxe_ilo

8. Restart the Ironic conductor service.::

    service ironic-conductor restart

Registering Proliant node in Ironic
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Nodes configured for iLO driver should have the ``driver`` property set to
``pxe_ilo``.  The following configuration values are also required in
``driver_info``:

- ``ilo_address``: IP address or hostname of the iLO.
- ``ilo_username``: Username for the iLO with administrator privileges.
- ``ilo_password``: Password for the above iLO user.
- ``pxe_deploy_kernel``: The Glance UUID of the deployment kernel.
- ``pxe_deploy_ramdisk``: The Glance UUID of the deployment ramdisk.
- ``client_port``: (optional) Port to be used for iLO operations if you are
  using a custom port on the iLO. Default port used is 443.
- ``client_timeout``: (optional) Timeout for iLO operations. Default timeout
  is 60 seconds.
- ``console_port``: (optional) Node's UDP port for console access. Any unused
  port on the Ironic conductor node may be used.

For example, you could run a similar command like below to enroll the Proliant
node::

  ironic node-create -d pxe_ilo ilo_address=<ilo-ip-address> -i ilo_username=<ilo-username> -i ilo_password=<ilo-password> -i pxe_deploy_kernel=<glance-uuid-of-pxe-deploy-kernel> pxe_deploy_ramdisk=<glance-uuid-of-deploy-ramdisk>

Boot modes
~~~~~~~~~~
Refer boot_mode_support_ for more information.

Functionalities across drivers
==============================

.. _boot_mode_support:

Boot mode support
^^^^^^^^^^^^^^^^^
The following drivers support automatic detection and setting of boot
mode (Legacy BIOS or UEFI).

* ``pxe_ilo``
* ``iscsi_ilo``

The boot modes can be configured in Ironic in the following way:

* When boot mode capability is not configured, these drivers preserve the
  current boot mode of the baremetal Proliant server. If operator/user
  doesn't care about boot modes for servers, then the boot mode capability
  need not be configured.

* Only one boot mode (either ``uefi`` or ``bios``) can be configured for
  the node.

* If the operator wants a node to boot always in ``uefi`` mode or ``bios``
  mode, then they may use ``capabilities`` parameter within ``properties``
  field of an Ironic node.

  To configure a node in ``uefi`` mode, then set ``capabilities`` as below::

    ironic node-update <node-uuid> add properties/capabilities='boot_mode:uefi'

  Nodes having ``boot_mode`` set to ``uefi`` may be requested by adding an
  ``extra_spec`` to the Nova flavor::

    nova flavor-key ironic-test-3 set capabilities:boot_mode="uefi"
    nova boot --flavor ironic-test-3 --image test-image instance-1

  If ``capabilities`` is used in ``extra_spec`` as above, Nova scheduler
  (``ComputeCapabilitesFilter``) will match only Ironic nodes which have
  the ``boot_mode`` set appropriately in ``properties/capabilities``. It will
  filter out rest of the nodes.

  The above facility for matching in Nova can be used in heterogenous
  environments where there is a mix of ``uefi`` and ``bios`` machines, and
  operator wants to provide a choice to the user regarding boot modes.  If the
  flavor doesn't contain ``boot_mode`` then Nova scheduler will not consider
  boot mode as a placement criteria, hence user may get either a BIOS or UEFI
  machine that matches with user specified flavors.


Currently for UEFI boot mode, automatic creation of boot ISO doesn't
work. The boot ISO for the deploy image needs to be built separately and the
deploy image's ``boot_iso`` property in Glance should contain the Glance UUID
of the boot ISO. For building boot ISO, add ``iso`` element to the
diskimage-builder command to build the image.  For example::

  disk-image-create ubuntu baremetal iso


References
==========
.. [1] HP iLO 4 User Guide - http://h20628.www2.hp.com/km-ext/kmcsdirect/emr_na-c03334051-11.pdf
.. [2] Proliantutils module - https://pypi.python.org/pypi/proliantutils
.. [3] DiskImage-Builder - https://github.com/openstack/diskimage-builder
.. [4] http://docs.openstack.org/developer/glance/configuring.html#configuring-the-swift-storage-backend
.. [5] Ironic Python Agent - https://github.com/openstack/ironic-python-agent
.. [6] https://wiki.openstack.org/wiki/Ironic/Drivers/iLODrivers

