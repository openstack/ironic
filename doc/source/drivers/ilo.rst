.. _ilo:

===========
iLO drivers
===========

Overview
========
iLO drivers enable to take advantage of features of iLO management engine in
HPE ProLiant servers.  iLO drivers are targeted for HPE ProLiant Gen 8 systems
and above which have `iLO 4 management engine <http://www8.hp.com/us/en/products/servers/ilo>`_.

For more detailed iLO driver document of Juno, Kilo and Liberty releases, and
up-to-date information (like tested platforms, known issues, etc), please check the
`iLO driver wiki page <https://wiki.openstack.org/wiki/Ironic/Drivers/iLODrivers>`_.

Currently there are 3 iLO drivers:

* ``iscsi_ilo``
* ``agent_ilo``
* ``pxe_ilo``.

The ``iscsi_ilo`` and ``agent_ilo`` drivers provide security enhanced
PXE-less deployment by using iLO virtual media to boot up the bare metal node.
These drivers send management info through management channel and separates
it from data channel which is used for deployment.

``iscsi_ilo`` and ``agent_ilo`` drivers use deployment ramdisk
built from ``diskimage-builder``. The ``iscsi_ilo`` driver deploys from
ironic conductor and supports both net-boot and local-boot of instance.
``agent_ilo`` deploys from bare metal node and always does local-boot.

``pxe_ilo`` driver uses PXE/iSCSI for deployment (just like normal PXE driver)
and deploys from ironic conductor. Additionally it supports automatic setting of
requested boot mode from nova. This driver doesn't require iLO Advanced license.


Prerequisites
=============

* `proliantutils <https://pypi.python.org/pypi/proliantutils>`_ is a python package
  which contains set of modules for managing HPE ProLiant hardware.

  Install ``proliantutils`` module on the ironic conductor node. Minimum
  version required is 2.1.5.::

   $ pip install "proliantutils>=2.1.5"

* ``ipmitool`` command must be present on the service node(s) where
  ``ironic-conductor`` is running. On most distros, this is provided as part
  of the ``ipmitool`` package.

Different Configuration for ilo drivers
=======================================

Glance Configuration
^^^^^^^^^^^^^^^^^^^^

1. Configure Glance image service with its storage backend as Swift. See
   `here <http://docs.openstack.org/developer/glance/configuring.html#configuring-the-swift-storage-backend>`_
   for configuration instructions.

2. Set a temp-url key for Glance user in Swift. For example, if you have
   configured Glance with user ``glance-swift`` and tenant as ``service``,
   then run the below command::

    swift --os-username=service:glance-swift post -m temp-url-key:mysecretkeyforglance

3. Fill the required parameters in the ``[glance]`` section   in
   ``/etc/ironic/ironic.conf``. Normally you would be required to fill in the
   following details.::

    [glance]
    swift_temp_url_key=mysecretkeyforglance
    swift_endpoint_url=https://10.10.1.10:8080
    swift_api_version=v1
    swift_account=AUTH_51ea2fb400c34c9eb005ca945c0dc9e1
    swift_container=glance

  The details can be retrieved by running the below command:

  .. code-block:: bash

   $ swift --os-username=service:glance-swift stat -v | grep -i url

   StorageURL:     http://10.10.1.10:8080/v1/AUTH_51ea2fb400c34c9eb005ca945c0dc9e1
   Meta Temp-Url-Key: mysecretkeyforglance


4. Swift must be accessible with the same admin credentials configured in
   Ironic. For example, if Ironic is configured with the below credentials in
   ``/etc/ironic/ironic.conf``.::

    [keystone_authtoken]
    admin_password = password
    admin_user = ironic
    admin_tenant_name = service

   Ensure ``auth_version`` in ``keystone_authtoken`` to 2.

   Then, the below command should work.:

   .. code-block:: bash

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

5. Restart the Ironic conductor service.::

    $ service ironic-conductor restart

Web server configuration on conductor
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

* The HTTP(S) web server can be configured in many ways. For apache
  web server on Ubuntu, refer `here <https://help.ubuntu.com/lts/serverguide/httpd.html>`_

* Following config variables need to be set in
  ``/etc/ironic/ironic.conf``:

  * ``use_web_server_for_images`` in ``[ilo]`` section::

     [ilo]
     use_web_server_for_images = True

  * ``http_url`` and ``http_root`` in ``[deploy]`` section::

     [deploy]
     # Ironic compute node's http root path. (string value)
     http_root=/httpboot

     # Ironic compute node's HTTP server URL. Example:
     # http://192.1.2.3:8080 (string value)
     http_url=http://192.168.0.2:8080

``use_web_server_for_images``: If the variable is set to ``false``, ``iscsi_ilo``
and ``agent_ilo`` uses swift containers to host the intermediate floppy
image and the boot ISO. If the variable is set to ``true``, these drivers
uses the local web server for hosting the intermediate files. The default value
for ``use_web_server_for_images`` is False.

``http_url``: The value for this variable is prefixed with the generated
intermediate files to generate a URL which is attached in the virtual media.

``http_root``: It is the directory location to which ironic conductor copies
the intermediate floppy image and the boot ISO.

.. note::
   HTTPS is strongly recommended over HTTP web server configuration for security
   enhancement. The ``iscsi_ilo`` and ``agent_ilo`` will send the instance's
   configdrive over an encrypted channel if web server is HTTPS enabled.

Enable driver
=============

1. Build a deploy ISO (and kernel and ramdisk) image, see :ref:`BuildingDibBasedDeployRamdisk`

2. See `Glance Configuration`_ for configuring glance image service with its storage
   backend as ``swift``.

3. Upload this image to Glance.::

    glance image-create --name deploy-ramdisk.iso --disk-format iso --container-format bare < deploy-ramdisk.iso

4. Add the driver name to the list of ``enabled_drivers`` in
   ``/etc/ironic/ironic.conf``.  For example, for `iscsi_ilo` driver::

    enabled_drivers = fake,pxe_ssh,pxe_ipmitool,iscsi_ilo

   Similarly it can be added for ``agent_ilo`` and ``pxe_ilo`` drivers.

5. Restart the ironic conductor service.::

    $ service ironic-conductor restart

Drivers
=======

iscsi_ilo driver
^^^^^^^^^^^^^^^^

Overview
~~~~~~~~
``iscsi_ilo`` driver was introduced as an alternative to ``pxe_ipmitool``
and ``pxe_ipminative`` drivers for HPE ProLiant servers. ``iscsi_ilo`` uses
virtual media feature in iLO to boot up the bare metal node instead of using
PXE or iPXE.

Target Users
~~~~~~~~~~~~

* Users who do not want to use PXE/TFTP protocol on their data centres.

* Users who have concerns with PXE protocol's security issues and want to have a
  security enhanced PXE-less deployment mechanism.

  The PXE driver passes management information in clear-text to the
  bare metal node.  However, if swift proxy server has an HTTPS
  endpoint (See :ref:`EnableHTTPSinSwift` for more information), the
  ``iscsi_ilo`` driver provides enhanced security by passing
  management information to and from swift endpoint over HTTPS.  The
  management information, deploy ramdisk and boot images for the instance will
  be retrieved over encrypted management network via iLO virtual media.

Tested Platforms
~~~~~~~~~~~~~~~~
This driver should work on HPE ProLiant Gen8 Servers and above with iLO 4.
It has been tested with the following servers:

* ProLiant DL380e Gen8
* ProLiant DL580 Gen8 UEFI
* ProLiant DL180 Gen9 UEFI
* ProLiant DL360 Gen9 UEFI
* ProLiant DL380 Gen9 UEFI

For more up-to-date information on server platform support info, refer
`iLO driver wiki page <https://wiki.openstack.org/wiki/Ironic/Drivers/iLODrivers>`_.

Features
~~~~~~~~
* PXE-less deploy with virtual media.
* Automatic detection of current boot mode.
* Automatic setting of the required boot mode, if UEFI boot mode is requested
  by the nova flavor's extra spec.
* Supports booting the instance from virtual media (netboot) as well as booting
  locally from disk. By default, the instance will always boot from virtual
  media for partition images.
* UEFI Boot Support
* UEFI Secure Boot Support
* Passing management information via secure, encrypted management network
  (virtual media) if swift proxy server has an HTTPS endpoint. See
  :ref:`EnableHTTPSinSwift` for more info.  User image provisioning is done
  using iSCSI over data network, so this driver has the benefit
  of security enhancement with the same performance. It segregates management
  info from data channel.
* Support for out-of-band cleaning operations.
* Remote Console
* HW Sensors
* Works well for machines with resource constraints (lesser amount of memory).
* Support for out-of-band hardware inspection.
* Swiftless deploy for intermediate images

Requirements
~~~~~~~~~~~~
* **iLO 4 Advanced License** needs to be installed on iLO to enable Virtual
  Media feature.
* **Swift Object Storage Service** - iLO driver uses swift to store temporary
  FAT images as well as boot ISO images.
* **Glance Image Service with swift configured as its backend** - When using
  ``iscsi_ilo`` driver, the image containing the deploy ramdisk is retrieved
  from swift directly by the iLO.


Deploy Process
~~~~~~~~~~~~~~

Refer to `Netboot with glance and swift`_ for the deploy process of partition image
and `Localboot with glance and swift`_ for the deploy process of whole disk image.

Configuring and Enabling the driver
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Refer to `Glance Configuration`_ and `Enable driver`_.

Registering ProLiant node in ironic
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Nodes configured for iLO driver should have the ``driver`` property set to
``iscsi_ilo``.  The following configuration values are also required in
``driver_info``:

- ``ilo_address``: IP address or hostname of the iLO.
- ``ilo_username``: Username for the iLO with administrator privileges.
- ``ilo_password``: Password for the above iLO user.
- ``ilo_deploy_iso``: The glance UUID of the deploy ramdisk ISO image.
- ``client_port``: (optional) Port to be used for iLO operations if you are
  using a custom port on the iLO.  Default port used is 443.
- ``client_timeout``: (optional) Timeout for iLO operations. Default timeout
  is 60 seconds.
- ``console_port``: (optional) Node's UDP port for console access. Any unused
  port on the ironic conductor node may be used.

For example, you could run a similar command like below to enroll the ProLiant
node::

  ironic node-create -d iscsi_ilo -i ilo_address=<ilo-ip-address> -i ilo_username=<ilo-username> -i ilo_password=<ilo-password> -i ilo_deploy_iso=<glance-uuid-of-deploy-iso>

Boot modes
~~~~~~~~~~
Refer to `Boot mode support`_ section for more information.

UEFI Secure Boot
~~~~~~~~~~~~~~~~
Refer to `UEFI Secure Boot Support`_ section for more information.

Node cleaning
~~~~~~~~~~~~~
Refer to `Node Cleaning Support`_ for more information.

Hardware Inspection
~~~~~~~~~~~~~~~~~~~
Refer to `Hardware Inspection Support`_ for more information.

Swiftless deploy for intermediate deploy and boot images
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Refer to `Swiftless deploy for intermediate images`_ for more information.

agent_ilo driver
^^^^^^^^^^^^^^^^

Overview
~~~~~~~~
``agent_ilo`` driver was introduced as an alternative to ``agent_ipmitool``
and ``agent_ipminative`` drivers for HPE ProLiant servers. ``agent_ilo`` driver
uses virtual media feature in HPE ProLiant bare metal servers to boot up the
Ironic Python Agent (IPA) on the bare metal node instead of using PXE. For
more information on IPA, refer
https://wiki.openstack.org/wiki/Ironic-python-agent.

Target Users
~~~~~~~~~~~~
* Users who do not want to use PXE/TFTP protocol on their data centres.
* Users who have concerns on PXE based agent driver's security and
  want to have a security enhanced PXE-less deployment mechanism.

  The PXE based agent drivers pass management information in clear-text to
  the bare metal node.  However, if swift proxy server has an HTTPS
  endpoint (See :ref:`EnableHTTPSinSwift` for more information),
  the ``agent_ilo`` driver provides enhanced security by passing authtoken
  and management information to and from swift endpoint over HTTPS.  The
  management information and deploy ramdisk will be retrieved over encrypted
  management network via iLO.

Tested Platforms
~~~~~~~~~~~~~~~~
This driver should work on HPE ProLiant Gen8 Servers and above with iLO 4.
It has been tested with the following servers:

* ProLiant DL380e Gen8
* ProLiant DL580e Gen8
* ProLiant DL360 Gen9 UEFI
* ProLiant DL380 Gen9 UEFI
* ProLiant DL180 Gen9 UEFI

For more up-to-date information, check the
`iLO driver wiki page <https://wiki.openstack.org/wiki/Ironic/Drivers/iLODrivers>`_.

Features
~~~~~~~~
* PXE-less deploy with virtual media using Ironic Python Agent(IPA).
* Support for out-of-band cleaning operations.
* Remote Console
* HW Sensors
* IPA runs on the bare metal node and pulls the image directly from swift.
* IPA deployed instances always boots from local disk.
* Segregates management info from data channel.
* UEFI Boot Support
* UEFI Secure Boot Support
* Support to use default in-band cleaning operations supported by
  Ironic Python Agent. For more details, see :ref:`InbandvsOutOfBandCleaning`.
* Support for out-of-band hardware inspection.
* Swiftless deploy for intermediate images.

Requirements
~~~~~~~~~~~~
* **iLO 4 Advanced License** needs to be installed on iLO to enable Virtual
  Media feature.
* **Swift Object Storage Service** - iLO driver uses swift to store temporary
  FAT images as well as boot ISO images.
* **Glance Image Service with swift configured as its backend** - When using
  ``agent_ilo`` driver, the image containing the agent is retrieved from
  swift directly by the iLO.

Deploy Process
~~~~~~~~~~~~~~

Refer to `Localboot with glance and swift`_ for details.

Configuring and Enabling the driver
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Refer to `Glance Configuration`_ and `Enable driver`_.

Registering ProLiant node in ironic
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Nodes configured for iLO driver should have the ``driver`` property set to
``agent_ilo``.  The following configuration values are also required in
``driver_info``:

- ``ilo_address``: IP address or hostname of the iLO.
- ``ilo_username``: Username for the iLO with administrator privileges.
- ``ilo_password``: Password for the above iLO user.
- ``ilo_deploy_iso``: The glance UUID of the deploy ramdisk ISO image.
- ``client_port``: (optional) Port to be used for iLO operations if you are
  using a custom port on the iLO.  Default port used is 443.
- ``client_timeout``: (optional) Timeout for iLO operations. Default timeout
  is 60 seconds.
- ``console_port``: (optional) Node's UDP port for console access. Any unused
  port on the ironic conductor node may be used.

For example, you could run a similar command like below to enroll the ProLiant
node::

  ironic node-create -d agent_ilo -i ilo_address=<ilo-ip-address> -i ilo_username=<ilo-username> -i ilo_password=<ilo-password> -i ilo_deploy_iso=<glance-uuid-of-deploy-iso>

Boot modes
~~~~~~~~~~
Refer to `Boot mode support`_ section for more information.

UEFI Secure Boot
~~~~~~~~~~~~~~~~
Refer to `UEFI Secure Boot Support`_ section for more information.

Node Cleaning
~~~~~~~~~~~~~
Refer to `Node Cleaning Support`_ for more information.

Hardware Inspection
~~~~~~~~~~~~~~~~~~~
Refer to `Hardware Inspection Support`_ for more information.

Swiftless deploy for intermediate deploy and boot images
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Refer to `Swiftless deploy for intermediate images`_ for more information.

pxe_ilo driver
^^^^^^^^^^^^^^

Overview
~~~~~~~~
``pxe_ilo`` driver uses PXE/iSCSI (just like ``pxe_ipmitool`` driver) to
deploy the image and uses iLO to do power and management operations on the
bare metal node(instead of using IPMI).

Target Users
~~~~~~~~~~~~
* Users who want to use PXE/iSCSI for deployment in their environment or who
  don't have Advanced License in their iLO.
* Users who don't want to configure boot mode manually on the bare metal node.

Tested Platforms
~~~~~~~~~~~~~~~~
This driver should work on HPE ProLiant Gen8 Servers and above with iLO 4.
It has been tested with the following servers:

* ProLiant DL380e Gen8
* ProLiant DL380e Gen8
* ProLiant DL580 Gen8 (BIOS/UEFI)
* ProLiant DL360 Gen9 UEFI
* ProLiant DL380 Gen9 UEFI

For more up-to-date information, check the
`iLO driver wiki page <https://wiki.openstack.org/wiki/Ironic/Drivers/iLODrivers>`_.

Features
~~~~~~~~
* Automatic detection of current boot mode.
* Automatic setting of the required boot mode, if UEFI boot mode is requested
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

2. Upload this image to glance.::

    glance image-create --name deploy-ramdisk.kernel --disk-format aki --container-format aki < deploy-ramdisk.kernel
    glance image-create --name deploy-ramdisk.initramfs --disk-format ari --container-format ari < deploy-ramdisk.initramfs

3. Add ``pxe_ilo`` to the list of ``enabled_drivers`` in
   ``/etc/ironic/ironic.conf``.  For example:::

    enabled_drivers = fake,pxe_ssh,pxe_ipmitool,pxe_ilo

4. Restart the ironic conductor service.::

    service ironic-conductor restart

Registering ProLiant node in ironic
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Nodes configured for iLO driver should have the ``driver`` property set to
``pxe_ilo``.  The following configuration values are also required in
``driver_info``:

- ``ilo_address``: IP address or hostname of the iLO.
- ``ilo_username``: Username for the iLO with administrator privileges.
- ``ilo_password``: Password for the above iLO user.
- ``deploy_kernel``: The glance UUID of the deployment kernel.
- ``deploy_ramdisk``: The glance UUID of the deployment ramdisk.
- ``client_port``: (optional) Port to be used for iLO operations if you are
  using a custom port on the iLO. Default port used is 443.
- ``client_timeout``: (optional) Timeout for iLO operations. Default timeout
  is 60 seconds.
- ``console_port``: (optional) Node's UDP port for console access. Any unused
  port on the ironic conductor node may be used.

For example, you could run a similar command like below to enroll the ProLiant
node::

  ironic node-create -d pxe_ilo -i ilo_address=<ilo-ip-address> -i ilo_username=<ilo-username> -i ilo_password=<ilo-password> -i deploy_kernel=<glance-uuid-of-pxe-deploy-kernel> -i deploy_ramdisk=<glance-uuid-of-deploy-ramdisk>

Boot modes
~~~~~~~~~~
Refer to `Boot mode support`_ section for more information.

UEFI Secure Boot
~~~~~~~~~~~~~~~~
Refer to `UEFI Secure Boot Support`_ section for more information.

Node Cleaning
~~~~~~~~~~~~~
Refer to `Node Cleaning Support`_ for more information.

Hardware Inspection
~~~~~~~~~~~~~~~~~~~
Refer to `Hardware Inspection Support`_ for more information.

Functionalities across drivers
==============================

Boot mode support
^^^^^^^^^^^^^^^^^
The following drivers support automatic detection and setting of boot
mode (Legacy BIOS or UEFI).

* ``pxe_ilo``
* ``iscsi_ilo``
* ``agent_ilo``

The boot modes can be configured in ironic in the following way:

* When boot mode capability is not configured, these drivers preserve the
  current boot mode of the bare metal ProLiant server. If operator/user
  doesn't care about boot modes for servers, then the boot mode capability
  need not be configured.

* Only one boot mode (either ``uefi`` or ``bios``) can be configured for
  the node.

* If the operator wants a node to boot always in ``uefi`` mode or ``bios``
  mode, then they may use ``capabilities`` parameter within ``properties``
  field of an ironic node.

  To configure a node in ``uefi`` mode, then set ``capabilities`` as below::

    ironic node-update <node-uuid> add properties/capabilities='boot_mode:uefi'

  Nodes having ``boot_mode`` set to ``uefi`` may be requested by adding an
  ``extra_spec`` to the nova flavor::

    nova flavor-key ironic-test-3 set capabilities:boot_mode="uefi"
    nova boot --flavor ironic-test-3 --image test-image instance-1

  If ``capabilities`` is used in ``extra_spec`` as above, nova scheduler
  (``ComputeCapabilitiesFilter``) will match only ironic nodes which have
  the ``boot_mode`` set appropriately in ``properties/capabilities``. It will
  filter out rest of the nodes.

  The above facility for matching in nova can be used in heterogeneous
  environments where there is a mix of ``uefi`` and ``bios`` machines, and
  operator wants to provide a choice to the user regarding boot modes.  If the
  flavor doesn't contain ``boot_mode`` then nova scheduler will not consider
  boot mode as a placement criteria, hence user may get either a BIOS or UEFI
  machine that matches with user specified flavors.


The automatic boot ISO creation for UEFI boot mode has been enabled in Kilo.
The manual creation of boot ISO for UEFI boot mode is also supported.
For the latter, the boot ISO for the deploy image needs to be built
separately and the deploy image's ``boot_iso`` property in glance should
contain the glance UUID of the boot ISO. For building boot ISO, add ``iso``
element to the diskimage-builder command to build the image.  For example::

  disk-image-create ubuntu baremetal iso

UEFI Secure Boot Support
^^^^^^^^^^^^^^^^^^^^^^^^
The following drivers support UEFI secure boot deploy:

* ``pxe_ilo``
* ``iscsi_ilo``
* ``agent_ilo``

The UEFI secure boot can be configured in ironic by adding
``secure_boot`` parameter in the ``capabilities`` parameter  within
``properties`` field of an ironic node.

``secure_boot`` is a boolean parameter and takes value as ``true`` or
``false``.

To enable ``secure_boot`` on a node add it to ``capabilities`` as below::

 ironic node-update <node-uuid> add properties/capabilities='secure_boot:true'

Alternatively use `Hardware Inspection`_ to populate the secure boot capability.

Nodes having ``secure_boot`` set to ``true`` may be requested by adding an
``extra_spec`` to the nova flavor::

  nova flavor-key ironic-test-3 set capabilities:secure_boot="true"
  nova boot --flavor ironic-test-3 --image test-image instance-1

If ``capabilities`` is used in ``extra_spec`` as above, nova scheduler
(``ComputeCapabilitiesFilter``) will match only ironic nodes which have
the ``secure_boot`` set appropriately in ``properties/capabilities``. It will
filter out rest of the nodes.

The above facility for matching in nova can be used in heterogeneous
environments where there is a mix of machines supporting and not supporting
UEFI secure boot, and operator wants to provide a choice to the user
regarding secure boot.  If the flavor doesn't contain ``secure_boot`` then
nova scheduler will not consider secure boot mode as a placement criteria,
hence user may get a secure boot capable machine that matches with user
specified flavors but deployment would not use its secure boot capability.
Secure boot deploy would happen only when it is explicitly specified through
flavor.

Use element ``ubuntu-signed`` or ``fedora`` to build signed deploy iso and
user images from
`diskimage-builder <https://pypi.python.org/pypi/diskimage-builder>`_.
Refer :ref:`BuildingDibBasedDeployRamdisk` for more information on building
deploy ramdisk.

The below command creates files named cloud-image-boot.iso, cloud-image.initrd,
cloud-image.vmlinuz and cloud-image.qcow2 in the current working directory.::

 cd <path-to-diskimage-builder>
 ./bin/disk-image-create -o cloud-image ubuntu-signed baremetal iso

.. note::
   In UEFI secure boot, digitally signed bootloader should be able to validate
   digital signatures of kernel during boot process. This requires that the
   bootloader contains the digital signatures of the kernel.
   For ``iscsi_ilo`` driver, it is recommended that ``boot_iso`` property for
   user image contains the glance UUID of the boot ISO.
   If ``boot_iso`` property is not updated in glance for the user image, it
   would create the ``boot_iso`` using bootloader from the deploy iso. This
   ``boot_iso`` will be able to boot the user image in UEFI secure boot
   environment only if the bootloader is signed and can validate digital
   signatures of user image kernel.

Ensure the public key of the signed image is loaded into bare metal to deploy
signed images.
For HPE ProLiant Gen9 servers, one can enroll public key using iLO System
Utilities UI. Please refer to section ``Accessing Secure Boot options`` in
`HP UEFI System Utilities User Guide <http://www.hp.com/ctg/Manual/c04398276.pdf>`_.
One can also refer to white paper on `Secure Boot for Linux on HP ProLiant
servers <http://h20195.www2.hp.com/V2/getpdf.aspx/4AA5-4496ENW.pdf>`_ for
additional details.

For more up-to-date information, refer
`iLO driver wiki page <https://wiki.openstack.org/wiki/Ironic/Drivers/iLODrivers>`_

.. _ilo_node_cleaning:

Node Cleaning Support
^^^^^^^^^^^^^^^^^^^^^
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
    Resets system ROM sttings to default. By default, enabled with priority 10.
    This clean step is supported only on Gen9 and above servers.
  -``reset_secure_boot_keys_to_default``:
    Resets secure boot keys to manufacturer's defaults. This step is supported
    only on Gen9 and above servers. By default, enabled with priority 20 .
  -``reset_ilo_credential``:
    Resets the iLO password, if ``ilo_change_password`` is specified as part of
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

* Configuration Options for the clean steps are listed under ``[ilo]`` section in
  ironic.conf ::

  - clean_priority_reset_ilo=1
  - clean_priority_reset_bios_to_default=10
  - clean_priority_reset_secure_boot_keys_to_default=20
  - clean_priority_clear_secure_boot_keys=0
  - clean_priority_reset_ilo_credential=30
  - clean_priority_erase_devices=10

For more information on node cleaning, see :ref:`cleaning`

Hardware Inspection Support
^^^^^^^^^^^^^^^^^^^^^^^^^^^

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

* ``pci_gpu_devices``: number of gpu devices connected to the bare metal.

* ``nic_capacity``: the max speed of the embedded NIC adapter.

The operator can specify these capabilities in nova flavor for node to be selected
for scheduling::

  nova flavor-key my-baremetal-flavor set capabilities:server_model="<in> Gen8"

  nova flavor-key my-baremetal-flavor set capabilities:pci_gpu_devices="> 0"

  nova flavor-key my-baremetal-flavor set capabilities:nic_capacity="10Gb"

  nova flavor-key my-baremetal-flavor set capabilities:ilo_firmware_version="<in> 2.10"

  nova flavor-key my-baremetal-flavor set capabilities:secure_boot="true"

Swiftless deploy for intermediate images
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

The ``iscsi_ilo`` and ``agent_ilo`` drivers can deploy and boot the server
with and without ``swift`` being used for hosting the intermediate
temporary floppy image (holding metadata for deploy kernel and ramdisk)
and the boot ISO (which is required for ``iscsi_ilo`` only). A local HTTP(S)
web server on each conductor node needs to be configured. Refer
`Web server configuration on conductor`_ for more information. The HTTPS
web server needs to be enabled (instead of HTTP web server) in order to
send management information and images in encrypted channel over HTTPS.

Deploy Process
~~~~~~~~~~~~~~

Refer to `Netboot in swiftless deploy for intermediate images`_ for partition
image support and refer to `Localboot in swiftless deploy for intermediate images`_
for whole disk image support.

Deploy Process
==============

Netboot with glance and swift
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

.. seqdiag::
   :scale: 80

   diagram {
      Glance; Conductor; Baremetal; Swift; IPA; iLO;
      activation = none;
      span_height = 1;
      edge_length = 250;
      default_note_color = white;
      default_fontsize = 14;

      Conductor -> iLO [label = "Powers off the node"];
      Conductor -> Glance [label = "Download user image"];
      Conductor -> Glance [label = "Get the metadata for deploy ISO"];
      Conductor -> Conductor [label = "Generates swift tempURL for deploy ISO"];
      Conductor -> Conductor [label = "Creates the FAT32 image containing Ironic API URL and driver name"];
      Conductor -> Swift [label = "Uploads the FAT32 image"];
      Conductor -> Conductor [label = "Generates swift tempURL for FAT32 image"];
      Conductor -> iLO [label = "Attaches the FAT32 image swift tempURL as virtual media floppy"];
      Conductor -> iLO [label = "Attaches the deploy ISO swift tempURL as virtual media CDROM"];
      Conductor -> iLO [label = "Sets one time boot to CDROM"];
      Conductor -> iLO [label = "Reboot the node"];
      iLO -> Swift [label = "Downloads deploy ISO"];
      Baremetal -> iLO [label = "Boots deploy kernel/ramdisk from iLO virtual media CDROM"];
      IPA -> Conductor [label = "Lookup node"];
      Conductor -> IPA [label = "Provides node UUID"];
      IPA -> Conductor [label = "Heartbeat"];
      Conductor -> IPA [label = "Exposes the disk over iSCSI"];
      Conductor -> Conductor [label = "Connects to bare metal's disk over iSCSI and writes image"];
      Conductor -> Conductor [label = "Generates the boot ISO"];
      Conductor -> Swift [label = "Uploads the boot ISO"];
      Conductor -> Conductor [label = "Generates swift tempURL for boot ISO"];
      Conductor -> iLO [label = "Attaches boot ISO swift tempURL as virtual media CDROM"];
      Conductor -> iLO [label = "Sets boot device to CDROM"];
      Conductor -> IPA [label = "Power off the node"];
      Conductor -> iLO [label = "Power on the node"];
      iLO -> Swift [label = "Downloads boot ISO"];
      iLO -> Baremetal [label = "Boots the instance kernel/ramdisk from iLO virtual media CDROM"];
      Baremetal -> Baremetal [label = "Instance kernel finds root partition and continues booting from disk"];
   }


Localboot with glance and swift
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

.. seqdiag::
   :scale: 80

   diagram {
      Glance; Conductor; Baremetal; Swift; IPA; iLO;
      activation = none;
      span_height = 1;
      edge_length = 250;
      default_note_color = white;
      default_fontsize = 14;

      Conductor -> iLO [label = "Powers off the node"];
      Conductor -> Glance [label = "Get the metadata for deploy ISO"];
      Glance -> Conductor [label = "Returns the metadata for deploy ISO"];
      Conductor -> Conductor [label = "Generates swift tempURL for deploy ISO"];
      Conductor -> Conductor [label = "Creates the FAT32 image containing ironic API URL and driver name"];
      Conductor -> Swift [label = "Uploads the FAT32 image"];
      Conductor -> Conductor [label = "Generates swift tempURL for FAT32 image"];
      Conductor -> iLO [label = "Attaches the FAT32 image swift tempURL as virtual media floppy"];
      Conductor -> iLO [label = "Attaches the deploy ISO swift tempURL as virtual media CDROM"];
      Conductor -> iLO [label = "Sets one time boot to CDROM"];
      Conductor -> iLO [label = "Reboot the node"];
      iLO -> Swift [label = "Downloads deploy ISO"];
      Baremetal -> iLO [label = "Boots deploy kernel/ramdisk from iLO virtual media CDROM"];
      IPA -> Conductor [label = "Lookup node"];
      Conductor -> IPA [label = "Provides node UUID"];
      IPA -> Conductor [label = "Heartbeat"];
      Conductor -> IPA [label = "Sends the user image HTTP(s) URL"];
      IPA -> Swift [label = "Retrieves the user image on bare metal"];
      IPA -> IPA [label = "Writes user image to disk"];
      IPA -> Conductor [label = "Heartbeat"];
      Conductor -> Baremetal [label = "Sets boot device to disk"];
      Conductor -> IPA [label = "Power off the node"];
      Conductor -> iLO [label = "Power on the node"];
      Baremetal -> Baremetal [label = "Boot user image from disk"];
   }

Netboot in swiftless deploy for intermediate images
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

.. seqdiag::
   :scale: 80

   diagram {
      Glance; Conductor; Baremetal; ConductorWebserver; IPA; iLO;
      activation = none;
      span_height = 1;
      edge_length = 250;
      default_note_color = white;
      default_fontsize = 14;

      Conductor -> iLO [label = "Powers off the node"];
      Conductor -> Glance [label = "Download user image"];
      Conductor -> Glance [label = "Get the metadata for deploy ISO"];
      Conductor -> Conductor [label = "Generates swift tempURL for deploy ISO"];
      Conductor -> Conductor [label = "Creates the FAT32 image containing Ironic API URL and driver name"];
      Conductor -> ConductorWebserver [label = "Uploads the FAT32 image"];
      Conductor -> iLO [label = "Attaches the FAT32 image URL as virtual media floppy"];
      Conductor -> iLO [label = "Attaches the deploy ISO swift tempURL as virtual media CDROM"];
      Conductor -> iLO [label = "Sets one time boot to CDROM"];
      Conductor -> iLO [label = "Reboot the node"];
      iLO -> Swift [label = "Downloads deploy ISO"];
      Baremetal -> iLO [label = "Boots deploy kernel/ramdisk from iLO virtual media CDROM"];
      IPA -> Conductor [label = "Lookup node"];
      Conductor -> IPA [label = "Provides node UUID"];
      IPA -> Conductor [label = "Heartbeat"];
      Conductor -> IPA [label = "Exposes the disk over iSCSI"];
      Conductor -> Conductor [label = "Connects to bare metal's disk over iSCSI and writes image"];
      Conductor -> Conductor [label = "Generates the boot ISO"];
      Conductor -> ConductorWebserver [label = "Uploads the boot ISO"];
      Conductor -> iLO [label = "Attaches boot ISO URL as virtual media CDROM"];
      Conductor -> iLO [label = "Sets boot device to CDROM"];
      Conductor -> IPA [label = "Power off the node"];
      Conductor -> iLO [label = "Power on the node"];
      iLO -> ConductorWebserver [label = "Downloads boot ISO"];
      iLO -> Baremetal [label = "Boots the instance kernel/ramdisk from iLO virtual media CDROM"];
      Baremetal -> Baremetal [label = "Instance kernel finds root partition and continues booting from disk"];
   }


Localboot in swiftless deploy for intermediate images
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

.. seqdiag::
   :scale: 80

   diagram {
      Glance; Conductor; Baremetal; ConductorWebserver; IPA; iLO;
      activation = none;
      span_height = 1;
      edge_length = 250;
      default_note_color = white;
      default_fontsize = 14;

      Conductor -> iLO [label = "Powers off the node"];
      Conductor -> Glance [label = "Get the metadata for deploy ISO"];
      Glance -> Conductor [label = "Returns the metadata for deploy ISO"];
      Conductor -> Conductor [label = "Generates swift tempURL for deploy ISO"];
      Conductor -> Conductor [label = "Creates the FAT32 image containing Ironic API URL and driver name"];
      Conductor -> ConductorWebserver [label = "Uploads the FAT32 image"];
      Conductor -> iLO [label = "Attaches the FAT32 image URL as virtual media floppy"];
      Conductor -> iLO [label = "Attaches the deploy ISO swift tempURL as virtual media CDROM"];
      Conductor -> iLO [label = "Sets one time boot to CDROM"];
      Conductor -> iLO [label = "Reboot the node"];
      iLO -> Swift [label = "Downloads deploy ISO"];
      Baremetal -> iLO [label = "Boots deploy kernel/ramdisk from iLO virtual media CDROM"];
      IPA -> Conductor [label = "Lookup node"];
      Conductor -> IPA [label = "Provides node UUID"];
      IPA -> Conductor [label = "Heartbeat"];
      Conductor -> IPA [label = "Sends the user image HTTP(s) URL"];
      IPA -> Swift [label = "Retrieves the user image on bare metal"];
      IPA -> IPA [label = "Writes user image to disk"];
      IPA -> Conductor [label = "Heartbeat"];
      Conductor -> Baremetal [label = "Sets boot device to disk"];
      Conductor -> IPA [label = "Power off the node"];
      Conductor -> Baremetal [label = "Power on the node"];
      Baremetal -> Baremetal [label = "Boot user image from disk"];
   }
