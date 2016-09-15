.. _ilo:

===========
iLO drivers
===========

Overview
========
iLO drivers enable to take advantage of features of iLO management engine in
HPE ProLiant servers.  iLO drivers are targeted for HPE ProLiant Gen 8 systems
and above which have `iLO 4 management engine <http://www8.hp.com/us/en/products/servers/ilo>`_.

For more details, please refer the iLO driver document of Juno, Kilo and Liberty releases,
and for up-to-date information (like tested platforms, known issues, etc), please check the
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
``agent_ilo`` deploys from bare metal node and supports both net-boot
and local-boot of instance.

``pxe_ilo`` driver uses PXE/iSCSI for deployment (just like normal PXE driver)
and deploys from ironic conductor. Additionally it supports automatic setting of
requested boot mode from nova. This driver doesn't require iLO Advanced license.


Prerequisites
=============

* `proliantutils <https://pypi.python.org/pypi/proliantutils>`_ is a python package
  which contains set of modules for managing HPE ProLiant hardware.

  Install ``proliantutils`` module on the ironic conductor node. Minimum
  version required is 2.1.11.::

   $ pip install "proliantutils>=2.1.11"

* ``ipmitool`` command must be present on the service node(s) where
  ``ironic-conductor`` is running. On most distros, this is provided as part
  of the ``ipmitool`` package. Refer to `Hardware Inspection Support`_ for more
  information on recommended version.

Different Configuration for ilo drivers
=======================================

Glance Configuration
^^^^^^^^^^^^^^^^^^^^

1. `Configure Glance image service with its storage backend as Swift
   <http://docs.openstack.org/developer/glance/configuring.html#configuring-the-swift-storage-backend>`_.

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
  bare metal node.  However, if swift proxy server and glance have HTTPS
  endpoints (See :ref:`EnableHTTPSinSwift`, :ref:`EnableHTTPSinGlance` for more
  information), the ``iscsi_ilo`` driver provides enhanced security by
  exchanging management information with swift and glance endpoints over HTTPS.
  The management information, deploy ramdisk and boot images for the instance
  will be retrieved over encrypted management network via iLO virtual media.

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
  (virtual media) if swift proxy server and glance have HTTPS endpoints. See
  :ref:`EnableHTTPSinSwift`, :ref:`EnableHTTPSinGlance` for more info.  User
  image provisioning is done using iSCSI over data network, so this driver has
  the benefit of security enhancement with the same performance. It segregates
  management info from data channel.
* Supports both out-of-band and in-band cleaning operations. For more details,
  see :ref:`InbandvsOutOfBandCleaning`.
* Remote Console
* HW Sensors
* Works well for machines with resource constraints (lesser amount of memory).
* Support for out-of-band hardware inspection.
* Swiftless deploy for intermediate images
* HTTP(S) Based Deploy.
* iLO drivers with standalone ironic.

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

Refer to `Netboot with glance and swift`_  and
`Localboot with glance and swift for partition images`_ for the deploy process
of partition image and `Localboot with glance and swift`_ for the deploy
process of whole disk image.

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
- ``ca_file``: (optional) CA certificate file to validate iLO.
- ``client_port``: (optional) Port to be used for iLO operations if you are
  using a custom port on the iLO.  Default port used is 443.
- ``client_timeout``: (optional) Timeout for iLO operations. Default timeout
  is 60 seconds.
- ``console_port``: (optional) Node's UDP port for console access. Any unused
  port on the ironic conductor node may be used.

.. note::
   To update SSL certificates into iLO, you can refer to `HPE Integrated
   Lights-Out Security Technology Brief <http://h20564.www2.hpe.com/hpsc/doc/public/display?docId=c04530504>`_.
   You can use iLO hostname or IP address as a 'Common Name (CN)' while
   generating Certificate Signing Request (CSR). Use the same value as
   `ilo_address` while enrolling node to Bare Metal service to avoid SSL
   certificate validation errors related to hostname mismatch.

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
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Refer to `Swiftless deploy for intermediate images`_ for more information.

HTTP(S) Based Deploy
~~~~~~~~~~~~~~~~~~~~
Refer to `HTTP(S) Based Deploy Support`_ for more information.

iLO drivers with standalone ironic
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Refer to `Support for iLO drivers with Standalone Ironic`_ for more information.

RAID Configuration
~~~~~~~~~~~~~~~~~~
Refer to `RAID Support`_ for more information.

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
  the bare metal node.  However, if swift proxy server and glance have HTTPS
  endpoints (See :ref:`EnableHTTPSinSwift`, :ref:`EnableHTTPSinGlance` for more
  information), the ``agent_ilo`` driver provides enhanced security by
  exchanging authtoken and management information with swift and glance
  endpoints over HTTPS.  The management information and deploy ramdisk will be
  retrieved over encrypted management network via iLO.

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
* Supports booting the instance from virtual media (netboot) as well as booting
  locally from disk. By default, the instance will always boot from virtual
  media for partition images.
* Segregates management info from data channel.
* UEFI Boot Support
* UEFI Secure Boot Support
* Support to use default in-band cleaning operations supported by
  Ironic Python Agent. For more details, see :ref:`InbandvsOutOfBandCleaning`.
* Support for out-of-band hardware inspection.
* Swiftless deploy for intermediate images.
* HTTP(S) Based Deploy.
* iLO drivers with standalone ironic.

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

Refer to `Netboot with glance and swift`_  and
`Localboot with glance and swift for partition images`_ for the deploy process
of partition image and `Localboot with glance and swift`_ for the deploy
process of whole disk image.

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
- ``ca_file``: (optional) CA certificate file to validate iLO.
- ``client_port``: (optional) Port to be used for iLO operations if you are
  using a custom port on the iLO.  Default port used is 443.
- ``client_timeout``: (optional) Timeout for iLO operations. Default timeout
  is 60 seconds.
- ``console_port``: (optional) Node's UDP port for console access. Any unused
  port on the ironic conductor node may be used.

.. note::
   To update SSL certificates into iLO, you can refer to `HPE Integrated
   Lights-Out Security Technology Brief <http://h20564.www2.hpe.com/hpsc/doc/public/display?docId=c04530504>`_.
   You can use iLO hostname or IP address as a 'Common Name (CN)' while
   generating Certificate Signing Request (CSR). Use the same value as
   `ilo_address` while enrolling node to Bare Metal service to avoid SSL
   certificate validation errors related to hostname mismatch.

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

HTTP(S) Based Deploy
~~~~~~~~~~~~~~~~~~~~
Refer to `HTTP(S) Based Deploy Support`_ for more information.

iLO drivers with standalone ironic
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Refer to `Support for iLO drivers with Standalone Ironic`_ for more information.

RAID Configuration
~~~~~~~~~~~~~~~~~~
Refer to `RAID Support`_ for more information.

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
* Supports both out-of-band and in-band cleaning operations. For more details,
  see :ref:`InbandvsOutOfBandCleaning`.
* Support for out-of-band hardware inspection.
* Supports UEFI Boot mode
* Supports UEFI Secure Boot
* HTTP(S) Based Deploy.

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
- ``ca_file``: (optional) CA certificate file to validate iLO.
- ``client_port``: (optional) Port to be used for iLO operations if you are
  using a custom port on the iLO. Default port used is 443.
- ``client_timeout``: (optional) Timeout for iLO operations. Default timeout
  is 60 seconds.
- ``console_port``: (optional) Node's UDP port for console access. Any unused
  port on the ironic conductor node may be used.

.. note::
   To update SSL certificates into iLO, you can refer to `HPE Integrated
   Lights-Out Security Technology Brief <http://h20564.www2.hpe.com/hpsc/doc/public/display?docId=c04530504>`_.
   You can use iLO hostname or IP address as a 'Common Name (CN)' while
   generating Certificate Signing Request (CSR). Use the same value as
   `ilo_address` while enrolling node to Bare Metal service to avoid SSL
   certificate validation errors related to hostname mismatch.

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

HTTP(S) Based Deploy
~~~~~~~~~~~~~~~~~~~~
Refer to `HTTP(S) Based Deploy Support`_ for more information.

iLO drivers with standalone ironic
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Refer to `Support for iLO drivers with Standalone Ironic`_ for more information.

RAID Configuration
~~~~~~~~~~~~~~~~~~
Refer to `RAID Support`_ for more information.

Functionalities across drivers
==============================

Boot mode support
^^^^^^^^^^^^^^^^^
The following drivers support automatic detection and setting of boot
mode (Legacy BIOS or UEFI).

* ``pxe_ilo``
* ``iscsi_ilo``
* ``agent_ilo``

* When boot mode capability is not configured:

  - If config variable ``default_boot_mode`` in ``[ilo]`` section of
    ironic configuration file is set to either 'bios' or 'uefi', then iLO
    drivers use that boot mode for provisioning the baremetal ProLiant
    servers.

  - If the pending boot mode is set on the node then iLO drivers use that boot
    mode for provisioning the baremetal ProLiant servers.

  - If the pending boot mode is not set on the node then iLO drivers use 'uefi'
    boot mode for UEFI capable servers and "bios" when UEFI is not supported.

* When boot mode capability is configured, the driver sets the pending boot
  mode to the configured value.

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

Alternatively see `Hardware Inspection Support`_ to know how to
automatically populate the secure boot capability.

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

For more information on node cleaning, see :ref:`cleaning`

Supported **Automated** Cleaning Operations
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

* The automated cleaning operations supported are:

  ``reset_bios_to_default``:
    Resets system ROM settings to default. By default, enabled with priority
    10. This clean step is supported only on Gen9 and above servers.
  ``reset_secure_boot_keys_to_default``:
    Resets secure boot keys to manufacturer's defaults. This step is supported
    only on Gen9 and above servers. By default, enabled with priority 20 .
  ``reset_ilo_credential``:
    Resets the iLO password, if ``ilo_change_password`` is specified as part of
    node's driver_info. By default, enabled with priority 30.
  ``clear_secure_boot_keys``:
    Clears all secure boot keys. This step is supported only on Gen9 and above
    servers. By default, this step is disabled.
  ``reset_ilo``:
    Resets the iLO. By default, this step is disabled.

* For in-band cleaning operations supported by ``agent_ilo`` driver, see
  :ref:`InbandvsOutOfBandCleaning`.

* All the automated cleaning steps have an explicit configuration option for
  priority. In order to disable or change the priority of the automated clean
  steps, respective configuration option for priority should be updated in
  ironic.conf.

* Updating clean step priority to 0, will disable that particular clean step
  and will not run during automated cleaning.

* Configuration Options for the automated clean steps are listed under
  ``[ilo]`` section in ironic.conf ::

  - clean_priority_reset_ilo=0
  - clean_priority_reset_bios_to_default=10
  - clean_priority_reset_secure_boot_keys_to_default=20
  - clean_priority_clear_secure_boot_keys=0
  - clean_priority_reset_ilo_credential=30

For more information on node automated cleaning, see :ref:`automated_cleaning`

Supported **Manual** Cleaning Operations
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

* The manual cleaning operations supported are:

  ``activate_license``:
    Activates the iLO Advanced license. This is an out-of-band manual cleaning
    step associated with the ``management`` interface. See
    `Activating iLO Advanced license as manual clean step`_ for user guidance
    on usage. Please note that this operation cannot be performed using virtual
    media based drivers like ``iscsi_ilo`` and ``agent_ilo`` as they need this
    type of advanced license already active to use virtual media to boot into
    to start cleaning operation. Virtual media is an advanced feature. If an
    advanced license is already active and the user wants to overwrite the
    current license key, for example in case of a multi-server activation key
    delivered with a flexible-quantity kit or after completing an Activation
    Key Agreement (AKA), then these drivers can still be used for executing
    this cleaning step.
  ``update_firmware``:
    Updates the firmware of the devices. Also an out-of-band step associated
    with the ``management`` interface. See
    `Initiating firmware update as manual clean step`_ for user guidance on
    usage. The supported devices for firmware update are: ``ilo``, ``cpld``,
    ``power_pic``, ``bios`` and ``chassis``. Refer to below table for their
    commonly used descriptions.

    .. csv-table::
       :header: "Device", "Description"
       :widths: 30, 80

       "``ilo``", "BMC for HPE ProLiant servers"
       "``cpld``", "System programmable logic device"
       "``power_pic``", "Power management controller"
       "``bios``", "HPE ProLiant System ROM"
       "``chassis``", "System chassis device"

    Some devices firmware cannot be updated via this method, such as: storage
    controllers, host bus adapters, disk drive firmware, network interfaces
    and Onboard Administrator (OA).

* iLO with firmware version 1.5 is minimally required to support all the
  operations.

For more information on node manual cleaning, see :ref:`manual_cleaning`

.. _ilo-inspection:

Hardware Inspection Support
^^^^^^^^^^^^^^^^^^^^^^^^^^^

The following iLO drivers support hardware inspection:

* ``pxe_ilo``
* ``iscsi_ilo``
* ``agent_ilo``

.. note::

   * The RAID needs to be pre-configured prior to inspection otherwise
     proliantutils returns 0 for disk size.

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

  .. note::

     * The capability ``nic_capacity`` can only be discovered if ipmitool
       version >= 1.8.15 is used on the conductor. The latest version can be
       downloaded from `here <http://sourceforge.net/projects/ipmitool/>`__.
     * The iLO firmware version needs to be 2.10 or above for nic_capacity to be
       discovered.

The operator can specify these capabilities in nova flavor for node to be selected
for scheduling::

  nova flavor-key my-baremetal-flavor set capabilities:server_model="<in> Gen8"

  nova flavor-key my-baremetal-flavor set capabilities:nic_capacity="10Gb"

  nova flavor-key my-baremetal-flavor set capabilities:ilo_firmware_version="<in> 2.10"

See :ref:`capabilities-discovery` for more details and examples.

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

.. note::
    This feature assumes that the user inputs are on Glance which uses swift
    as backend. If swift dependency has to be eliminated, please refer to
    `HTTP(S) Based Deploy Support`_ also.

Deploy Process
~~~~~~~~~~~~~~

Refer to `Netboot in swiftless deploy for intermediate images`_ for partition
image support and refer to `Localboot in swiftless deploy for intermediate images`_
for whole disk image support.

HTTP(S) Based Deploy Support
^^^^^^^^^^^^^^^^^^^^^^^^^^^^

The user input for the images given in ``driver_info`` like ``ilo_deploy_iso``,
``deploy_kernel`` and ``deploy_ramdisk`` and in ``instance_info`` like
``image_source``, ``kernel``, ``ramdisk`` and ``ilo_boot_iso`` may also be given as
HTTP(S) URLs.

The HTTP(S) web server can be configured in many ways. For the Apache
web server on Ubuntu, refer `here <https://help.ubuntu.com/lts/serverguide/httpd.html>`_.
The web server may reside on a different system than the conductor nodes, but its URL
must be reachable by the conductor and the bare metal nodes.

Deploy Process
~~~~~~~~~~~~~~

Refer to `Netboot with HTTP(S) based deploy`_ for partition image boot and refer to
`Localboot with HTTP(S) based deploy`_ for whole disk image boot.


Support for iLO drivers with Standalone Ironic
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

It is possible to use ironic as standalone services without other
OpenStack services. iLO drivers can be used in standalone ironic.
This feature is referred to as ``iLO drivers with standalone ironic`` in this document and is
supported by following drivers:

* ``pxe_ilo``
* ``iscsi_ilo``
* ``agent_ilo``

Configuration
~~~~~~~~~~~~~
The HTTP(S) web server needs to be configured as described in `HTTP(S) Based Deploy Support`_
and `Web server configuration on conductor`_ needs to be configured for hosting
intermediate images on conductor as described in
`Swiftless deploy for intermediate images`_.

Deploy Process
~~~~~~~~~~~~~~
``iscsi_ilo`` and ``agent_ilo`` supports both netboot and localboot. Refer
to `Netboot in standalone ironic`_ and `Localboot in standalone ironic`_
for details of deploy process for netboot and localboot respectively.
For ``pxe_ilo``, the deploy process is same as native ``pxe_ipmitool`` driver.

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

Localboot with glance and swift for partition images
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

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
      Conductor -> IPA [label = "Sends the user image HTTP(S) URL"];
      IPA -> Swift [label = "Retrieves the user image on bare metal"];
      IPA -> IPA [label = "Writes user image to root partition"];
      IPA -> IPA [label = "Installs boot loader"];
      IPA -> Conductor [label = "Heartbeat"];
      Conductor -> Baremetal [label = "Sets boot device to disk"];
      Conductor -> IPA [label = "Power off the node"];
      Conductor -> iLO [label = "Power on the node"];
      Baremetal -> Baremetal [label = "Boot user image from disk"];
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
      Conductor -> IPA [label = "Sends the user image HTTP(S) URL"];
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
      Conductor -> IPA [label = "Sends the user image HTTP(S) URL"];
      IPA -> Swift [label = "Retrieves the user image on bare metal"];
      IPA -> IPA [label = "Writes user image to disk"];
      IPA -> Conductor [label = "Heartbeat"];
      Conductor -> Baremetal [label = "Sets boot device to disk"];
      Conductor -> IPA [label = "Power off the node"];
      Conductor -> Baremetal [label = "Power on the node"];
      Baremetal -> Baremetal [label = "Boot user image from disk"];
   }

Netboot with HTTP(S) based deploy
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

.. seqdiag::
   :scale: 80

   diagram {
      Webserver; Conductor; Baremetal; Swift; IPA; iLO;
      activation = none;
      span_height = 1;
      edge_length = 250;
      default_note_color = white;
      default_fontsize = 14;

      Conductor -> iLO [label = "Powers off the node"];
      Conductor -> Webserver [label = "Download user image"];
      Conductor -> Conductor [label = "Creates the FAT32 image containing Ironic API URL and driver name"];
      Conductor -> Swift [label = "Uploads the FAT32 image"];
      Conductor -> Conductor [label = "Generates swift tempURL for FAT32 image"];
      Conductor -> iLO [label = "Attaches the FAT32 image swift tempURL as virtual media floppy"];
      Conductor -> iLO [label = "Attaches the deploy ISO URL as virtual media CDROM"];
      Conductor -> iLO [label = "Sets one time boot to CDROM"];
      Conductor -> iLO [label = "Reboot the node"];
      iLO -> Webserver [label = "Downloads deploy ISO"];
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

Localboot with HTTP(S) based deploy
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

.. seqdiag::
   :scale: 80

   diagram {
      Webserver; Conductor; Baremetal; Swift; IPA; iLO;
      activation = none;
      span_height = 1;
      edge_length = 250;
      default_note_color = white;
      default_fontsize = 14;

      Conductor -> iLO [label = "Powers off the node"];
      Conductor -> Conductor [label = "Creates the FAT32 image containing ironic API URL and driver name"];
      Conductor -> Swift [label = "Uploads the FAT32 image"];
      Conductor -> Conductor [label = "Generates swift tempURL for FAT32 image"];
      Conductor -> iLO [label = "Attaches the FAT32 image swift tempURL as virtual media floppy"];
      Conductor -> iLO [label = "Attaches the deploy ISO URL as virtual media CDROM"];
      Conductor -> iLO [label = "Sets one time boot to CDROM"];
      Conductor -> iLO [label = "Reboot the node"];
      iLO -> Webserver [label = "Downloads deploy ISO"];
      Baremetal -> iLO [label = "Boots deploy kernel/ramdisk from iLO virtual media CDROM"];
      IPA -> Conductor [label = "Lookup node"];
      Conductor -> IPA [label = "Provides node UUID"];
      IPA -> Conductor [label = "Heartbeat"];
      Conductor -> IPA [label = "Sends the user image HTTP(S) URL"];
      IPA -> Webserver [label = "Retrieves the user image on bare metal"];
      IPA -> IPA [label = "Writes user image to disk"];
      IPA -> Conductor [label = "Heartbeat"];
      Conductor -> Baremetal [label = "Sets boot device to disk"];
      Conductor -> IPA [label = "Power off the node"];
      Conductor -> Baremetal [label = "Power on the node"];
      Baremetal -> Baremetal [label = "Boot user image from disk"];
   }

Netboot in standalone ironic
^^^^^^^^^^^^^^^^^^^^^^^^^^^^

.. seqdiag::
   :scale: 80

   diagram {
      Webserver; Conductor; Baremetal; ConductorWebserver; IPA; iLO;
      activation = none;
      span_height = 1;
      edge_length = 250;
      default_note_color = white;
      default_fontsize = 14;

      Conductor -> iLO [label = "Powers off the node"];
      Conductor -> Webserver [label = "Download user image"];
      Conductor -> Conductor [label = "Creates the FAT32 image containing Ironic API URL and driver name"];
      Conductor -> ConductorWebserver[label = "Uploads the FAT32 image"];
      Conductor -> iLO [label = "Attaches the FAT32 image URL as virtual media floppy"];
      Conductor -> iLO [label = "Attaches the deploy ISO URL as virtual media CDROM"];
      Conductor -> iLO [label = "Sets one time boot to CDROM"];
      Conductor -> iLO [label = "Reboot the node"];
      iLO -> Webserver [label = "Downloads deploy ISO"];
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

Localboot in standalone ironic
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

.. seqdiag::
   :scale: 80

   diagram {
      Webserver; Conductor; Baremetal; ConductorWebserver; IPA; iLO;
      activation = none;
      span_height = 1;
      edge_length = 250;
      default_note_color = white;
      default_fontsize = 14;

      Conductor -> iLO [label = "Powers off the node"];
      Conductor -> Conductor [label = "Creates the FAT32 image containing Ironic API URL and driver name"];
      Conductor -> ConductorWebserver [label = "Uploads the FAT32 image"];
      Conductor -> Conductor [label = "Generates URL for FAT32 image"];
      Conductor -> iLO [label = "Attaches the FAT32 image URL as virtual media floppy"];
      Conductor -> iLO [label = "Attaches the deploy ISO URL as virtual media CDROM"];
      Conductor -> iLO [label = "Sets one time boot to CDROM"];
      Conductor -> iLO [label = "Reboot the node"];
      iLO -> Webserver [label = "Downloads deploy ISO"];
      Baremetal -> iLO [label = "Boots deploy kernel/ramdisk from iLO virtual media CDROM"];
      IPA -> Conductor [label = "Lookup node"];
      Conductor -> IPA [label = "Provides node UUID"];
      IPA -> Conductor [label = "Heartbeat"];
      Conductor -> IPA [label = "Sends the user image HTTP(S) URL"];
      IPA -> Webserver [label = "Retrieves the user image on bare metal"];
      IPA -> IPA [label = "Writes user image to disk"];
      IPA -> Conductor [label = "Heartbeat"];
      Conductor -> Baremetal [label = "Sets boot device to disk"];
      Conductor -> IPA [label = "Power off the node"];
      Conductor -> Baremetal [label = "Power on the node"];
      Baremetal -> Baremetal [label = "Boot user image from disk"];
   }

Activating iLO Advanced license as manual clean step
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
iLO drivers can activate the iLO Advanced license key as a manual cleaning
step. Any manual cleaning step can only be initiated when a node is in the
``manageable`` state. Once the manual cleaning is finished, the node will be
put in the ``manageable`` state again. User can follow steps from
:ref:`manual_cleaning` to initiate manual cleaning operation on a node.

An example of a manual clean step with ``activate_license`` as the only clean
step could be::

    "clean_steps": [{
        "interface": "management",
        "step": "activate_license",
        "args": {
            "ilo_license_key": "ABC12-XXXXX-XXXXX-XXXXX-YZ345"
        }
    }]

The different attributes of ``activate_license`` clean step are as follows:

  .. csv-table::
   :header: "Attribute", "Description"
   :widths: 30, 120

   "``interface``", "Interface of clean step, here ``management``"
   "``step``", "Name of clean step, here ``activate_license``"
   "``args``", "Keyword-argument entry (<name>: <value>) being passed to clean step"
   "``args.ilo_license_key``", "iLO Advanced license key to activate enterprise features. This is mandatory."

Initiating firmware update as manual clean step
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
iLO drivers can invoke secure firmware update as a manual cleaning step. Any
manual cleaning step can only be initiated when a node is in the ``manageable``
state. Once the manual cleaning is finished, the node will be put in the
``manageable`` state again. A user can follow steps from :ref:`manual_cleaning`
to initiate manual cleaning operation on a node.

An example of a manual clean step with ``update_firmware`` as the only clean
step could be::

    "clean_steps": [{
        "interface": "management",
        "step": "update_firmware",
        "args": {
            "firmware_update_mode": "ilo",
            "firmware_images":[
                {
                    "url": "file:///firmware_images/ilo/1.5/CP024444.scexe",
                    "checksum": "a94e683ea16d9ae44768f0a65942234d",
                    "component": "ilo"
                },
                {
                    "url": "swift://firmware_container/cpld2.3.rpm",
                    "checksum": "<md5-checksum-of-this-file>",
                    "component": "cpld"
                },
                {
                    "url": "http://my_address:port/firmwares/bios_vLatest.scexe",
                    "checksum": "<md5-checksum-of-this-file>",
                    "component": "bios"
                },
                {
                    "url": "https://my_secure_address_url/firmwares/chassis_vLatest.scexe",
                    "checksum": "<md5-checksum-of-this-file>",
                    "component": "chassis"
                },
                {
                    "url": "file:///home/ubuntu/firmware_images/power_pic/pmc_v3.0.bin",
                    "checksum": "<md5-checksum-of-this-file>",
                    "component": "power_pic"
                }
            ]
        }
    }]

The different attributes of ``update_firmware`` clean step are as follows:

  .. csv-table::
   :header: "Attribute", "Description"
   :widths: 30, 120

   "``interface``", "Interface of clean step, here ``management``"
   "``step``", "Name of clean step, here ``update_firmware``"
   "``args``", "Keyword-argument entry (<name>: <value>) being passed to clean step"
   "``args.firmware_update_mode``", "Mode (or mechanism) of out-of-band firmware update. Supported value is ``ilo``. This is mandatory."
   "``args.firmware_images``", "Ordered list of dictionaries of images to be flashed. This is mandatory."

Each firmware image block is represented by a dictionary (JSON), in the form::

    {
      "url": "<url of firmware image file>",
      "checksum": "<md5 checksum of firmware image file to verify the image>",
      "component": "<device on which firmware image will be flashed>"
    }

All the fields in the firmware image block are mandatory.

* The different types of firmware url schemes supported are:
  ``file``, ``http``, ``https`` and ``swift``.

.. note::
   This feature assumes that while using ``file`` url scheme the file path is
   on the conductor controlling the node.

.. note::
   The ``swift`` url scheme assumes the swift account of the ``service``
   project. The ``service`` project (tenant) is a special project created in
   the Keystone system designed for the use of the core OpenStack services.
   When Ironic makes use of Swift for storage purpose, the account is generally
   ``service`` and the container is generally ``ironic`` and ``ilo`` drivers
   use a container named ``ironic_ilo_container`` for their own purpose.

.. note::
   While using firmware files with a ``.rpm`` extension, make sure the commands
   ``rpm2cpio`` and ``cpio`` are present on the conductor, as they are utilized
   to extract the firmware image from the package.

* The firmware components that can be updated are:
  ``ilo``, ``cpld``, ``power_pic``, ``bios`` and ``chassis``.
* The firmware images will be updated in the order given by the operator. If
  there is any error during processing of any of the given firmware images
  provided in the list, none of the firmware updates will occur. The processing
  error could happen during image download, image checksum verification or
  image extraction. The logic is to process each of the firmware files and
  update them on the devices only if all the files are processed successfully.
  If, during the update (uploading and flashing) process, an update fails, then
  the remaining updates, if any, in the list will be aborted. But it is
  recommended to triage and fix the failure and re-attempt the manual clean
  step ``update_firmware`` for the aborted ``firmware_images``.

  The devices for which the firmwares have been updated successfully would
  start functioning using their newly updated firmware.
* As a troubleshooting guidance on the complete process, check Ironic conductor
  logs carefully to see if there are any firmware processing or update related
  errors which may help in root causing or gain an understanding of where
  things were left off or where things failed. You can then fix or work around
  and then try again. A common cause of update failure is HPE Secure Digital
  Signature check failure for the firmware image file.
* To compute ``md5`` checksum for your image file, you can use the following
  command::

    $ md5sum image.rpm
    66cdb090c80b71daa21a67f06ecd3f33  image.rpm

RAID Support
^^^^^^^^^^^^

The inband RAID functionality is now supported by iLO drivers.
See :ref:`raid` for more information.

.. _DIB_raid_support:

DIB support for Proliant Hardware Manager
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

To create an agent ramdisk with ``Proliant Hardware Manager``,
use the ``proliant-tools`` element in DIB::

  disk-image-create -o proliant-agent-ramdisk ironic-agent fedora proliant-tools

