.. _ilo:

===========
iLO drivers
===========

Overview
========
iLO drivers enable to take advantage of features of iLO management engine in
HP Proliant servers.  iLO drivers are targeted for HP Proliant Gen 8 systems
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
  version required is 2.1.1.::

   $ pip install "proliantutils>=2.1.1"

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
* ProLiant DL580 Gen8 UEFI
* ProLiant DL180 Gen9 UEFI
* ProLiant DL360 Gen9 UEFI
* ProLiant DL380 Gen9 UEFI

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
* UEFI Secure Boot Support
* Passing authentication token via secure, encrypted management network
  (Virtual Media). Provisioning is done using iSCSI over data network
  (like PXE driver), so this driver has the  benefit of security
  enhancement with the same performance. Hence it segregates management info
  from data channel.
* Support for out-of-band cleaning operations.
* Remote Console
* HW Sensors
* Works well for machines with resource constraints (lesser amount of memory).
* Support for out-of-band hardware inspection.

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

1. Build a deploy ISO image, see :ref:`BuildingDibBasedDeployRamdisk`

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
Refer to `Boot mode support`_ section for more information.

UEFI Secure Boot
~~~~~~~~~~~~~~~~
Refer to `UEFI Secure Boot support`_ section for more information.

Node cleaning
~~~~~~~~~~~~~
Refer to ilo_node_cleaning_ for more information.

Hardware Inspection
~~~~~~~~~~~~~~~~~~~
Refer to hardware_inspection_ for more information.

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
* ProLiant DL360 Gen9 UEFI
* ProLiant DL380 Gen9 UEFI

This driver supports only Gen 8 Class 0 systems (BIOS only).  For
more up-to-date information, check the iLO driver wiki [6]_.

Features
~~~~~~~~
* PXE-less deploy with Virtual Media using Ironic Python Agent.
* Support for out-of-band cleaning operations.
* Remote Console
* HW Sensors
* IPA runs on the baremetal node and pulls the image directly from Swift.
* IPA deployed instances always boots from local disk.
* Segregates management info from data channel.
* UEFI Boot Support
* UEFI Secure Boot Support
* Support to use default in-band cleaning operations supported by
  Ironic Python Agent. For more details, see :ref:`InbandvsOutOfBandCleaning`.
* Support for out-of-band hardware inspection.

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

1. Build a deploy ISO image, see :ref:`BuildingCoreOSDeployRamdisk`.

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

Boot modes
~~~~~~~~~~
Refer to `Boot mode support`_ section for more information.

UEFI Secure Boot
~~~~~~~~~~~~~~~~
Refer to `UEFI Secure Boot support`_ section for more information.

Node Cleaning
~~~~~~~~~~~~~
Refer to ilo_node_cleaning_ for more information.

Hardware Inspection
~~~~~~~~~~~~~~~~~~~
Refer to hardware_inspection_ for more information.

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
* ProLiant DL360 Gen9 UEFI
* ProLiant DL380 Gen9 UEFI

The driver doesn't work on BIOS mode on DL580 Gen8 and Gen9 systems due to
an issue in the firmware.  For information on this, refer iLO driver
wiki [6]_.

For more up-to-date information, check the iLO driver wiki [6]_.

Features
~~~~~~~~
* Automatic detection of current boot mode.
* Automatic setting of the required boot mode if UEFI boot mode is requested
  by the nova flavor's extra spec.
* Support for out-of-band cleaning operations.
* Support for out-of-band hardware inspection.
* Supports UEFI Boot mode
* Supports UEFI Secure Boot

Requirements
~~~~~~~~~~~~
None.

Configuring and Enabling the driver
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

1. Build a deploy image, see :ref:`BuildingDibBasedDeployRamdisk`

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
- ``deploy_kernel``: The Glance UUID of the deployment kernel.
- ``deploy_ramdisk``: The Glance UUID of the deployment ramdisk.
- ``client_port``: (optional) Port to be used for iLO operations if you are
  using a custom port on the iLO. Default port used is 443.
- ``client_timeout``: (optional) Timeout for iLO operations. Default timeout
  is 60 seconds.
- ``console_port``: (optional) Node's UDP port for console access. Any unused
  port on the Ironic conductor node may be used.

For example, you could run a similar command like below to enroll the Proliant
node::

  ironic node-create -d pxe_ilo -i ilo_address=<ilo-ip-address> -i ilo_username=<ilo-username> -i ilo_password=<ilo-password> -i deploy_kernel=<glance-uuid-of-pxe-deploy-kernel> -i deploy_ramdisk=<glance-uuid-of-deploy-ramdisk>

Boot modes
~~~~~~~~~~
Refer to `Boot mode support`_ section for more information.

UEFI Secure Boot
~~~~~~~~~~~~~~~~
Refer to `UEFI Secure Boot support`_ section for more information.

Node Cleaning
~~~~~~~~~~~~~
Refer to ilo_node_cleaning_ for more information.

Hardware Inspection
~~~~~~~~~~~~~~~~~~~
Refer to hardware_inspection_ for more information.

Functionalities across drivers
==============================

Boot mode support
^^^^^^^^^^^^^^^^^
The following drivers support automatic detection and setting of boot
mode (Legacy BIOS or UEFI).

* ``pxe_ilo``
* ``iscsi_ilo``
* ``agent_ilo``

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
  (``ComputeCapabilitiesFilter``) will match only Ironic nodes which have
  the ``boot_mode`` set appropriately in ``properties/capabilities``. It will
  filter out rest of the nodes.

  The above facility for matching in Nova can be used in heterogeneous
  environments where there is a mix of ``uefi`` and ``bios`` machines, and
  operator wants to provide a choice to the user regarding boot modes.  If the
  flavor doesn't contain ``boot_mode`` then Nova scheduler will not consider
  boot mode as a placement criteria, hence user may get either a BIOS or UEFI
  machine that matches with user specified flavors.


The automatic boot ISO creation for UEFI boot mode has been enabled in Kilo.
The manual creation of boot ISO for UEFI boot mode is also supported.
For the latter, the boot ISO for the deploy image needs to be built
separately and the deploy image's ``boot_iso`` property in Glance should
contain the Glance UUID of the boot ISO. For building boot ISO, add ``iso``
element to the diskimage-builder command to build the image.  For example::

  disk-image-create ubuntu baremetal iso

UEFI Secure Boot support
^^^^^^^^^^^^^^^^^^^^^^^^
The following drivers support UEFI secure boot deploy:

* ``pxe_ilo``
* ``iscsi_ilo``
* ``agent_ilo``

The UEFI secure boot mode can be configured in Ironic by adding
``secure_boot`` parameter in the ``capabilities`` parameter  within
``properties`` field of an Ironic node.

``secure_boot`` is a boolean parameter and takes value as ``true`` or
``false``.

To enable ``secure_boot`` on a node add it to ``capabilities`` as below::

 ironic node-update <node-uuid> add properties/capabilities='secure_boot:true'

Alternatively use hardware_inspection_ to populate the secure boot capability.

Nodes having ``secure_boot`` set to ``true`` may be requested by adding an
``extra_spec`` to the Nova flavor::

  nova flavor-key ironic-test-3 set capabilities:secure_boot="true"
  nova boot --flavor ironic-test-3 --image test-image instance-1

If ``capabilities`` is used in ``extra_spec`` as above, Nova scheduler
(``ComputeCapabilitiesFilter``) will match only Ironic nodes which have
the ``secure_boot`` set appropriately in ``properties/capabilities``. It will
filter out rest of the nodes.

The above facility for matching in Nova can be used in heterogeneous
environments where there is a mix of machines supporting and not supporting
UEFI secure boot, and operator wants to provide a choice to the user
regarding secure boot.  If the flavor doesn't contain ``secure_boot`` then
Nova scheduler will not consider secure boot mode as a placement criteria,
hence user may get a secure boot capable machine that matches with user
specified flavors but deployment would not use its secure boot capability.
Secure boot deploy would happen only when it is explicitly specified through
flavor.

Use element ``ubuntu-signed`` or ``fedora`` to build signed deploy iso and
user images from ``diskimage-builder`` [3]_.

The below command creates files named ``deploy-ramdisk.kernel``,
``deploy-ramdisk.initramfs`` and ``deploy-ramdisk.iso`` in the current
working directory.::

 cd <path-to-diskimage-builder>
 ./bin/ramdisk-image-create -o deploy-ramdisk ubuntu-signed deploy-ironic iso

The below command creates files named cloud-image-boot.iso, cloud-image.initrd,
cloud-image.vmlinuz and cloud-image.qcow2 in the current working directory.::

 cd <path-to-diskimage-builder>
 ./bin/disk-image-create -o cloud-image ubuntu-signed baremetal iso

.. note::
   In UEFI secure boot, digitally signed bootloader should be able to validate
   digital signatures of kernel during boot process. This requires that the
   bootloader contains the digital signatures of the kernel.
   For ``iscsi_ilo`` driver, it is recommended that ``boot_iso`` property for
   user image contains the Glance UUID of the boot ISO.
   If ``boot_iso`` property is not updated in Glance for the user image, it
   would create the ``boot_iso`` using bootloader from the deploy iso. This
   ``boot_iso`` will be able to boot the user image in UEFI secure boot
   environment only if the bootloader is signed and can validate digital
   signatures of user image kernel.

Ensure the public key of the signed image is loaded into baremetal to deploy
signed images.
For HP Proliant Gen9 servers, one can enroll public key using iLO System
Utilities UI. Please refer to section ``Accessing Secure Boot options`` in
HP UEFI System Utilities User Guide. [7]_
One can also refer to white paper on Secure Boot for Linux on HP Proliant
servers for additional details. [8]_

For more up-to-date information, refer to the ``UEFI Secure Boot support``
section in the iLO driver (Kilo release) wiki [10]_.

.. _ilo_node_cleaning:

Node Cleaning
^^^^^^^^^^^^^
The following iLO drivers support node cleaning -

* ``pxe_ilo``
* ``iscsi_ilo``
* ``agent_ilo``

Supported Cleaning Operations
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

* The cleaning operations supported are:

  -``reset_ilo``:
    Resets the iLO. By default, enabled with priority 1.
  -``reset_bios_to_default``:
    Resets BIOS Settings to default. By default, enabled with priority 10.
    This clean step is supported only on Gen9 and above servers.
  -``reset_secure_boot_keys_to_default``:
    Resets secure boot keys to manufacturer's defaults. This step is supported
    only on Gen9 and above servers. By default, enabled with priority 20 .
  -``reset_ilo_credential``:
    Resets the iLO password, if 'ilo_change_password' is specified as part of
    node's driver_info. By default, enabled with priority 30.
  -``clear_secure_boot_keys``:
    Clears all secure boot keys. This step is supported only on Gen9 and above
    servers. By default, this step is disabled.

* For in-band cleaning operations supported by ``agent_ilo`` driver, see
  :ref:`InbandvsOutOfBandCleaning`.

* All the cleaning steps have an explicit configuration option for priority.
  In order to disable or change the priority of the clean steps, respective
  configuration option for priority should be updated in ironic.conf.

* Updating clean step priority to 0, will disable that particular clean step
  and will not run during cleaning.

* Configuration Options for the clean steps are listed under [ilo] section in
  ironic.conf ::

  - clean_priority_reset_ilo=1
  - clean_priority_reset_bios_to_default=10
  - clean_priority_reset_secure_boot_keys_to_default=20
  - clean_priority_clear_secure_boot_keys=0
  - clean_priority_reset_ilo_credential=30
  - clean_priority_erase_devices=10

For more information on node cleaning, see [9]_.

.. _hardware_inspection:

Hardware Inspection
^^^^^^^^^^^^^^^^^^^

The following iLO drivers support hardware inspection:

* ``pxe_ilo``
* ``iscsi_ilo``
* ``agent_ilo``

.. note::

   * The RAID needs to be pre-configured prior to inspection otherwise
     proliantutils returns 0 for disk size.
   * The iLO firmware version needs to be 2.10 or above for nic_capacity to be
     discovered.

The inspection process will discover the following essential properties
(properties required for scheduling deployment):

* ``memory_mb``: memory size

* ``cpus``: number of cpus

* ``cpu_arch``: cpu architecture

* ``local_gb``: disk size

Inspection can also discover the following extra capabilities for iLO drivers:

* ``ilo_firmware_version``: iLO firmware version

* ``rom_firmware_version``: ROM firmware version

* ``secure_boot``: secure boot is supported or not. The possible values are
  'true' or 'false'. The value is returned as 'true' if secure boot is supported
  by the server.

* ``server_model``: server model

* ``pci_gpu_devices``: number of gpu devices connected to the baremetal.

* ``nic_capacity``: the max speed of the embedded NIC adapter.

The operator can specify these capabilities in nova flavor for node to be selected
for scheduling::

  nova flavor-key my-baremetal-flavor set capabilities:server_model="<in> Gen8"

  nova flavor-key my-baremetal-flavor set capabilities:pci_gpu_devices="> 0"

  nova flavor-key my-baremetal-flavor set capabilities:nic_capacity="10Gb"

  nova flavor-key my-baremetal-flavor set capabilities:ilo_firmware_version="<in> 2.10"

  nova flavor-key my-baremetal-flavor set capabilities:secure_boot="true"

References
==========
.. [1] HP iLO 4 User Guide - http://h20628.www2.hp.com/km-ext/kmcsdirect/emr_na-c03334051-11.pdf
.. [2] Proliantutils module - https://pypi.python.org/pypi/proliantutils
.. [3] DiskImage-Builder - https://github.com/openstack/diskimage-builder
.. [4] http://docs.openstack.org/developer/glance/configuring.html#configuring-the-swift-storage-backend
.. [5] Ironic Python Agent - https://github.com/openstack/ironic-python-agent
.. [6] https://wiki.openstack.org/wiki/Ironic/Drivers/iLODrivers
.. [7] HP UEFI System Utilities User Guide - http://www.hp.com/ctg/Manual/c04398276.pdf
.. [8] Secure Boot for Linux on HP Proliant servers http://h20195.www2.hp.com/V2/getpdf.aspx/4AA5-4496ENW.pdf
.. [9] http://docs.openstack.org/developer/ironic/deploy/cleaning.html
.. [10] https://wiki.openstack.org/wiki/Ironic/Drivers/iLODrivers/Kilo
