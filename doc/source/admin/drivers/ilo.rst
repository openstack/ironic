.. _ilo:

==========
iLO driver
==========

Overview
========
iLO driver enables to take advantage of features of iLO management engine in
HPE ProLiant servers. The ``ilo`` hardware type is targeted for HPE ProLiant
Gen8 and Gen9 systems which have `iLO 4 management engine`_. From **Pike**
release ``ilo`` hardware type supports ProLiant Gen10 systems which have
`iLO 5 management engine`_. iLO5 conforms to `Redfish`_ API and hence hardware
type ``redfish`` (see :doc:`redfish`) is also an option for this kind of
hardware but it lacks the iLO specific features.

For more details and for up-to-date information (like tested platforms,
known issues, etc), please check the `iLO driver wiki page <https://wiki.openstack.org/wiki/Ironic/Drivers/iLODrivers>`_.

For enabling Gen10 systems and getting detailed information on Gen10 feature
support in Ironic please check this `Gen10 wiki section`_.

Hardware type
=============

ProLiant hardware is primarily supported by the ``ilo`` hardware type. ``ilo5``
hardware type is only supported on ProLiant Gen10 and later systems. Both
hardware can be used with reference hardware type ``ipmi`` (see
:doc:`ipmitool`) and ``redfish`` (see :doc:`redfish`). For information on how
to enable the ``ilo`` and ``ilo5`` hardware type, see
:ref:`enable-hardware-types`.

.. note::
   Only HPE ProLiant Gen10 servers supports hardware type ``redfish``.

The hardware type ``ilo`` supports following HPE server features:

* `Boot mode support`_
* `UEFI Secure Boot Support`_
* `Node Cleaning Support`_
* `Node Deployment Customization`_
* `Hardware Inspection Support`_
* `Swiftless deploy for intermediate images`_
* `HTTP(S) Based Deploy Support`_
* `Support for iLO driver with Standalone Ironic`_
* `RAID Support`_
* `Disk Erase Support`_
* `Initiating firmware update as manual clean step`_
* `Smart Update Manager (SUM) based firmware update`_
* `Activating iLO Advanced license as manual clean step`_
* `Firmware based UEFI iSCSI boot from volume support`_
* `Certificate based validation in iLO`_
* `Rescue mode support`_
* `Inject NMI support`_
* `Soft power operation support`_
* `BIOS configuration support`_
* `IPv6 support`_

Apart from above features hardware type ``ilo5`` also supports following
features:

* `Out of Band RAID Support`_
* `Out of Band Sanitize Disk Erase Support`_
* `Out of Band One Button Secure Erase Support`_
* `UEFI-HTTPS Boot support`_

Hardware interfaces
^^^^^^^^^^^^^^^^^^^

The ``ilo`` hardware type supports following hardware interfaces:

* bios
    Supports ``ilo`` and ``no-bios``. The default is ``ilo``.
    They can be enabled by using the ``[DEFAULT]enabled_bios_interfaces``
    option in ``ironic.conf`` as given below:

    .. code-block:: ini

        [DEFAULT]
        enabled_hardware_types = ilo
        enabled_bios_interfaces = ilo,no-bios

* boot
    Supports ``ilo-virtual-media``, ``ilo-pxe`` and ``ilo-ipxe``. The
    default is ``ilo-virtual-media``. The ``ilo-virtual-media`` interface
    provides security enhanced PXE-less deployment by using iLO virtual
    media to boot up the bare metal node. The ``ilo-pxe`` and ``ilo-ipxe``
    interfaces use PXE and iPXE respectively for deployment(just like
    :ref:`pxe-boot`). These interfaces do not require iLO Advanced license.
    They can be enabled by using the ``[DEFAULT]enabled_boot_interfaces``
    option in ``ironic.conf`` as given below:

    .. code-block:: ini

        [DEFAULT]
        enabled_hardware_types = ilo
        enabled_boot_interfaces = ilo-virtual-media,ilo-pxe,ilo-ipxe

* console
    Supports ``ilo`` and ``no-console``. The default is ``ilo``.
    They can be enabled by using the ``[DEFAULT]enabled_console_interfaces``
    option in ``ironic.conf`` as given below:

    .. code-block:: ini

        [DEFAULT]
        enabled_hardware_types = ilo
        enabled_console_interfaces = ilo,no-console

    .. note::
       To use ``ilo`` console interface you need to enable iLO feature
       'IPMI/DCMI over LAN Access' on
       `iLO4 <https://support.hpe.com/hpsc/doc/public/display?docId=c03334051>`_
       and `iLO5 <https://support.hpe.com/hpsc/doc/public/display?docId=a00018324en_us>`_
       management engine.

* inspect
    Supports ``ilo`` and ``inspector``. The default is ``ilo``. They
    can be enabled by using the ``[DEFAULT]enabled_inspect_interfaces`` option
    in ``ironic.conf`` as given below:

    .. code-block:: ini

        [DEFAULT]
        enabled_hardware_types = ilo
        enabled_inspect_interfaces = ilo,inspector

    .. note::
       :ironic-inspector-doc:`Ironic Inspector <>`
       needs to be configured to use ``inspector`` as the inspect interface.

* management
    Supports only ``ilo``. It can be enabled by using the
    ``[DEFAULT]enabled_management_interfaces`` option in ``ironic.conf`` as
    given below:

    .. code-block:: ini

        [DEFAULT]
        enabled_hardware_types = ilo
        enabled_management_interfaces = ilo

* power
    Supports only ``ilo``. It can be enabled by using the
    ``[DEFAULT]enabled_power_interfaces`` option in ``ironic.conf`` as given
    below:

    .. code-block:: ini

        [DEFAULT]
        enabled_hardware_types = ilo
        enabled_power_interfaces = ilo

* raid
    Supports ``agent`` and ``no-raid``. The default is ``no-raid``.
    They can be enabled by using the ``[DEFAULT]enabled_raid_interfaces``
    option in ``ironic.conf`` as given below:

    .. code-block:: ini

        [DEFAULT]
        enabled_hardware_types = ilo
        enabled_raid_interfaces = agent,no-raid

* storage
    Supports ``cinder`` and ``noop``. The default is ``noop``.
    They can be enabled by using the ``[DEFAULT]enabled_storage_interfaces``
    option in ``ironic.conf`` as given below:

    .. code-block:: ini

        [DEFAULT]
        enabled_hardware_types = ilo
        enabled_storage_interfaces = cinder,noop

    .. note::
       The storage interface ``cinder`` is supported only when corresponding
       boot interface of the ``ilo`` hardware type based node is ``ilo-pxe``
       or ``ilo-ipxe``. Please refer to :doc:`/admin/boot-from-volume` for
       configuring ``cinder`` as a storage interface.

* rescue
    Supports ``agent`` and ``no-rescue``. The default is ``no-rescue``.
    They can be enabled by using the ``[DEFAULT]enabled_rescue_interfaces``
    option in ``ironic.conf`` as given below:

    .. code-block:: ini

        [DEFAULT]
        enabled_hardware_types = ilo
        enabled_rescue_interfaces = agent,no-rescue


The ``ilo5`` hardware type supports all the ``ilo`` interfaces described above,
except for ``boot`` and ``raid`` interfaces. The details of ``boot`` and
``raid`` interfaces is as under:

* raid
    Supports ``ilo5`` and ``no-raid``. The default is ``ilo5``.
    They can be enabled by using the ``[DEFAULT]enabled_raid_interfaces``
    option in ``ironic.conf`` as given below:

    .. code-block:: ini

        [DEFAULT]
        enabled_hardware_types = ilo5
        enabled_raid_interfaces = ilo5,no-raid

* boot
    Supports ``ilo-uefi-https`` apart from the other boot interfaces supported
    by ``ilo`` hardware type.
    This can be enabled by using the ``[DEFAULT]enabled_boot_interfaces``
    option in ``ironic.conf`` as given below:

    .. code-block:: ini

        [DEFAULT]
        enabled_hardware_types = ilo5
        enabled_boot_interfaces = ilo-uefi-https,ilo-virtual-media



The ``ilo`` and ``ilo5`` hardware type support all standard ``deploy`` and
``network`` interface implementations, see :ref:`enable-hardware-interfaces`
for details.

The following command can be used to enroll a ProLiant node with
``ilo`` hardware type:

.. code-block:: console

    openstack baremetal node create --os-baremetal-api-version=1.38 \
        --driver ilo \
        --deploy-interface direct \
        --raid-interface agent \
        --rescue-interface agent \
        --driver-info ilo_address=<ilo-ip-address> \
        --driver-info ilo_username=<ilo-username> \
        --driver-info ilo_password=<ilo-password> \
        --driver-info ilo_deploy_iso=<glance-uuid-of-deploy-iso> \
        --driver-info ilo_rescue_iso=<glance-uuid-of-rescue-iso>

The following command can be used to enroll a ProLiant node with
``ilo5`` hardware type:

.. code-block:: console

    openstack baremetal node create \
        --driver ilo5 \
        --deploy-interface direct \
        --raid-interface ilo5 \
        --rescue-interface agent \
        --driver-info ilo_address=<ilo-ip-address> \
        --driver-info ilo_username=<ilo-username> \
        --driver-info ilo_password=<ilo-password> \
        --driver-info ilo_deploy_iso=<glance-uuid-of-deploy-iso> \
        --driver-info ilo_rescue_iso=<glance-uuid-of-rescue-iso>

Please refer to :doc:`/install/enabling-drivers` for detailed
explanation of hardware type.

Node configuration
^^^^^^^^^^^^^^^^^^

* Each node is configured for ``ilo`` and ``ilo5`` hardware type by setting
  the following ironic node object's properties in ``driver_info``:

  - ``ilo_address``: IP address or hostname of the iLO.
  - ``ilo_username``: Username for the iLO with administrator privileges.
  - ``ilo_password``: Password for the above iLO user.
  - ``client_port``: (optional) Port to be used for iLO operations if you are
    using a custom port on the iLO.  Default port used is 443.
  - ``client_timeout``: (optional) Timeout for iLO operations. Default timeout
    is 60 seconds.
  - ``ca_file``: (optional) CA certificate file to validate iLO.
  - ``console_port``: (optional) Node's UDP port for console access. Any unused
    port on the ironic conductor node may be used. This is required only when
    ``ilo-console`` interface is used.

* The following properties are also required in node object's
  ``driver_info`` if ``ilo-virtual-media`` boot interface is used:

  - ``ilo_deploy_iso``: The glance UUID of the deploy ramdisk ISO image.
  - ``instance info/ilo_boot_iso`` property to be either boot iso
    Glance UUID or a HTTP(S) URL. This is optional property and is used when
    ``boot_option`` is set to ``netboot`` or ``ramdisk``.

    .. note::
       When ``boot_option`` is set to ``ramdisk``, the ironic node must be
       configured to use ``ramdisk`` deploy interface. See :ref:`ramdisk-deploy`
       for details.

  - ``ilo_rescue_iso``: The glance UUID of the rescue ISO image. This is optional
    property and is used when ``rescue`` interface is set to ``agent``.

* The following properties are also required in node object's
  ``driver_info`` if ``ilo-pxe`` or ``ilo-ipxe`` boot interface is used:

  - ``deploy_kernel``: The glance UUID or a HTTP(S) URL of the deployment kernel.
  - ``deploy_ramdisk``: The glance UUID or a HTTP(S) URL of the deployment ramdisk.
  - ``rescue_kernel``: The glance UUID or a HTTP(S) URL of the rescue kernel.
    This is optional property and is used when ``rescue`` interface is set to
    ``agent``.
  - ``rescue_ramdisk``: The glance UUID or a HTTP(S) URL of the rescue ramdisk.
    This is optional property and is used when ``rescue`` interface is set to
    ``agent``.

* The following properties are also required in node object's
  ``driver_info`` if ``ilo-uefi-https`` boot interface is used for ``ilo5``
  hardware type:

  - ``ilo_deploy_kernel``: The glance UUID or a HTTPS URL of the deployment kernel.
  - ``ilo_deploy_ramdisk``: The glance UUID or a HTTPS URL of the deployment ramdisk.
  - ``ilo_bootloader``: The glance UUID or a HTTPS URL of the bootloader.
  - ``ilo_rescue_kernel``: The glance UUID or a HTTPS URL of the rescue kernel.
    This is optional property and is used when ``rescue`` interface is set to
    ``agent``.
  - ``ilo_rescue_ramdisk``: The glance UUID or a HTTP(S) URL of the rescue ramdisk.
    This is optional property and is used when ``rescue`` interface is set to
    ``agent``.

    .. note::
       ``ilo-uefi-https`` boot interface is supported by only ``ilo5`` hardware
       type. If the images are not hosted in glance, the references
       must be HTTPS URLs hosted by secure webserver. This boot interface can
       be used only when the current boot mode is ``UEFI``.


* The  following parameters are mandatory in ``driver_info``
  if ``ilo-inspect`` inspect inteface is used and SNMPv3 inspection
  (`SNMPv3 Authentication` in `HPE iLO4 User Guide`_) is desired:

  * ``snmp_auth_user`` : The SNMPv3 user.

  * ``snmp_auth_prot_password`` : The auth protocol pass phrase.

  * ``snmp_auth_priv_password`` : The privacy protocol pass phrase.

  The  following parameters are optional for SNMPv3 inspection:

  * ``snmp_auth_protocol`` : The Auth Protocol. The valid values
    are "MD5" and "SHA". The iLO default value is "MD5".

  * ``snmp_auth_priv_protocol`` : The Privacy protocol. The valid
    values are "AES" and "DES". The iLO default value is "DES".

.. note::
   If configuration values for ``ca_file``, ``client_port`` and
   ``client_timeout`` are not provided in the ``driver_info`` of the node,
   the corresponding config variables defined under ``[ilo]`` section in
   ironic.conf will be used.

Prerequisites
=============

* `proliantutils <https://pypi.org/project/proliantutils>`_ is a python package
  which contains a set of modules for managing HPE ProLiant hardware.

  Install ``proliantutils`` module on the ironic conductor node. Minimum
  version required is 2.8.0::

   $ pip install "proliantutils>=2.8.0"

* ``ipmitool`` command must be present on the service node(s) where
  ``ironic-conductor`` is running. On most distros, this is provided as part
  of the ``ipmitool`` package. Please refer to `Hardware Inspection Support`_
  for more information on recommended version.

Different configuration for ilo hardware type
=============================================

Glance Configuration
^^^^^^^^^^^^^^^^^^^^

1. :glance-doc:`Configure Glance image service with its storage backend as Swift
   <configuration/configuring.html#configuring-the-swift-storage-backend>`.

2. Set a temp-url key for Glance user in Swift. For example, if you have
   configured Glance with user ``glance-swift`` and tenant as ``service``,
   then run the below command::

    swift --os-username=service:glance-swift post -m temp-url-key:mysecretkeyforglance

3. Fill the required parameters in the ``[glance]`` section   in
   ``/etc/ironic/ironic.conf``. Normally you would be required to fill in the
   following details::

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
   ``/etc/ironic/ironic.conf``::

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

5. Restart the Ironic conductor service::

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

``use_web_server_for_images``: If the variable is set to ``false``,
the ``ilo-virtual-media`` boot interface uses swift containers to host the
intermediate floppy image and the boot ISO. If the variable is set to
``true``, it uses the local web server for hosting the intermediate files.
The default value for ``use_web_server_for_images`` is False.

``http_url``: The value for this variable is prefixed with the generated
intermediate files to generate a URL which is attached in the virtual media.

``http_root``: It is the directory location to which ironic conductor copies
the intermediate floppy image and the boot ISO.

.. note::
   HTTPS is strongly recommended over HTTP web server configuration for security
   enhancement. The ``ilo-virtual-media`` boot interface will send the instance's
   configdrive over an encrypted channel if web server is HTTPS enabled. However
   for ``ilo-uefi-https`` boot interface HTTPS webserver is mandatory as this
   interface only supports HTTPS URLs.

Enable driver
=============

1. Build a deploy ISO (and kernel and ramdisk) image, see :ref:`deploy-ramdisk`

2. See `Glance Configuration`_ for configuring glance image service with its storage
   backend as ``swift``.

3. Upload this image to Glance::

    glance image-create --name deploy-ramdisk.iso --disk-format iso --container-format bare < deploy-ramdisk.iso

4. Enable hardware type and hardware interfaces in
   ``/etc/ironic/ironic.conf``::

    [DEFAULT]
    enabled_hardware_types = ilo
    enabled_bios_interfaces = ilo
    enabled_boot_interfaces = ilo-virtual-media,ilo-pxe,ilo-ipxe
    enabled_power_interfaces = ilo
    enabled_console_interfaces = ilo
    enabled_raid_interfaces = agent
    enabled_management_interfaces = ilo
    enabled_inspect_interfaces = ilo
    enabled_rescue_interfaces = agent

5. Restart the ironic conductor service::

    $ service ironic-conductor restart

Optional functionalities for the ``ilo`` hardware type
======================================================

Boot mode support
^^^^^^^^^^^^^^^^^
The hardware type ``ilo`` supports automatic detection and setting
of boot mode (Legacy BIOS or UEFI).

* When boot mode capability is not configured:

  - If config variable ``default_boot_mode`` in ``[ilo]`` section of
    ironic configuration file is set to either 'bios' or 'uefi', then iLO
    driver uses that boot mode for provisioning the baremetal ProLiant
    servers.

  - If the pending boot mode is set on the node then iLO driver uses that boot
    mode for provisioning the baremetal ProLiant servers.

  - If the pending boot mode is not set on the node then iLO driver uses 'uefi'
    boot mode for UEFI capable servers and "bios" when UEFI is not supported.

* When boot mode capability is configured, the driver sets the pending boot
  mode to the configured value.

* Only one boot mode (either ``uefi`` or ``bios``) can be configured for
  the node.

* If the operator wants a node to boot always in ``uefi`` mode or ``bios``
  mode, then they may use ``capabilities`` parameter within ``properties``
  field of an ironic node.

  To configure a node in ``uefi`` mode, then set ``capabilities`` as below::

    openstack baremetal node set <node-uuid> --property capabilities='boot_mode:uefi'

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


.. _`iLO UEFI Secure Boot Support`:

UEFI Secure Boot Support
^^^^^^^^^^^^^^^^^^^^^^^^
The hardware type ``ilo`` supports secure boot deploy.

The UEFI secure boot can be configured in ironic by adding
``secure_boot`` parameter in the ``capabilities`` parameter  within
``properties`` field of an ironic node.

``secure_boot`` is a boolean parameter and takes value as ``true`` or
``false``.

To enable ``secure_boot`` on a node add it to ``capabilities`` as below::

 openstack baremetal node set <node-uuid> --property capabilities='secure_boot:true'

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
`diskimage-builder <https://pypi.org/project/diskimage-builder>`_.
Please refer to :ref:`deploy-ramdisk` for more information on building
deploy ramdisk.

The below command creates files named cloud-image-boot.iso, cloud-image.initrd,
cloud-image.vmlinuz and cloud-image.qcow2 in the current working directory::

 cd <path-to-diskimage-builder>
 ./bin/disk-image-create -o cloud-image ubuntu-signed baremetal iso

.. note::
   In UEFI secure boot, digitally signed bootloader should be able to validate
   digital signatures of kernel during boot process. This requires that the
   bootloader contains the digital signatures of the kernel.
   For the ``ilo-virtual-media`` boot interface, it is recommended that
   ``boot_iso`` property for user image contains the glance UUID of the boot
   ISO.  If ``boot_iso`` property is not updated in glance for the user image,
   it would create the ``boot_iso`` using bootloader from the deploy iso. This
   ``boot_iso`` will be able to boot the user image in UEFI secure boot
   environment only if the bootloader is signed and can validate digital
   signatures of user image kernel.

Ensure the public key of the signed image is loaded into bare metal to deploy
signed images.
For HPE ProLiant Gen9 servers, one can enroll public key using iLO System
Utilities UI. Please refer to section ``Accessing Secure Boot options`` in
`HP UEFI System Utilities User Guide <https://h20628.www2.hp.com/km-ext/kmcsdirect/emr_na-c03886429-5.pdf>`_.
One can also refer to white paper on `Secure Boot for Linux on HP ProLiant
servers <https://h50146.www5.hpe.com/products/software/oe/linux/mainstream/support/whitepaper/pdfs/2018_rev2_4AA5-4496ENW.pdf>`_ for
additional details.

For more up-to-date information, refer
`iLO driver wiki page <https://wiki.openstack.org/wiki/Ironic/Drivers/iLODrivers>`_

.. _ilo_node_cleaning:

Node Cleaning Support
^^^^^^^^^^^^^^^^^^^^^
The hardware type ``ilo`` and ``ilo5`` supports node cleaning.

For more information on node cleaning, see :ref:`cleaning`

Supported **Automated** Cleaning Operations
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

* The automated cleaning operations supported are:

  * ``reset_bios_to_default``:
    Resets system ROM settings to default. By default, enabled with priority
    10. This clean step is supported only on Gen9 and above servers.
  * ``reset_secure_boot_keys_to_default``:
    Resets secure boot keys to manufacturer's defaults. This step is supported
    only on Gen9 and above servers. By default, enabled with priority 20 .
  * ``reset_ilo_credential``:
    Resets the iLO password, if ``ilo_change_password`` is specified as part of
    node's driver_info. By default, enabled with priority 30.
  * ``clear_secure_boot_keys``:
    Clears all secure boot keys. This step is supported only on Gen9 and above
    servers. By default, this step is disabled.
  * ``reset_ilo``:
    Resets the iLO. By default, this step is disabled.
  * ``erase_devices``:
    An inband clean step that performs disk erase on all the disks including
    the disks visible to OS as well as the raw disks visible to Smart
    Storage Administrator (SSA). This step supports erasing of the raw disks
    visible to SSA in Proliant servers only with the ramdisk created using
    diskimage-builder from Ocata release. By default, this step is disabled.
    See `Disk Erase Support`_ for more details.

* For supported in-band cleaning operations, see
  :ref:`InbandvsOutOfBandCleaning`.

* All the automated cleaning steps have an explicit configuration option for
  priority. In order to disable or change the priority of the automated clean
  steps, respective configuration option for priority should be updated in
  ironic.conf.

* Updating clean step priority to 0, will disable that particular clean step
  and will not run during automated cleaning.

* Configuration Options for the automated clean steps are listed under
  ``[ilo]`` and ``[deploy]`` section in ironic.conf ::

   [ilo]
   clean_priority_reset_ilo=0
   clean_priority_reset_bios_to_default=10
   clean_priority_reset_secure_boot_keys_to_default=20
   clean_priority_clear_secure_boot_keys=0
   clean_priority_reset_ilo_credential=30

   [deploy]
   erase_devices_priority=0

For more information on node automated cleaning, see :ref:`automated_cleaning`

Supported **Manual** Cleaning Operations
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

* The manual cleaning operations supported are:

  ``activate_license``:
    Activates the iLO Advanced license. This is an out-of-band manual cleaning
    step associated with the ``management`` interface. See
    `Activating iLO Advanced license as manual clean step`_ for user guidance
    on usage. Please note that this operation cannot be performed using the
    ``ilo-virtual-media`` boot interface as it needs this
    type of advanced license already active to use virtual media to boot into
    to start cleaning operation. Virtual media is an advanced feature. If an
    advanced license is already active and the user wants to overwrite the
    current license key, for example in case of a multi-server activation key
    delivered with a flexible-quantity kit or after completing an Activation
    Key Agreement (AKA), then the driver can still be used for executing
    this cleaning step.
  ``apply_configuration``:
    Applies given BIOS settings on the node. See
    `BIOS configuration support`_. This step is part of the ``bios`` interface.
  ``factory_reset``:
    Resets the BIOS settings on the node to factory defaults. See
    `BIOS configuration support`_. This step is part of the ``bios`` interface.
  ``create_configuration``:
    Applies RAID configuration on the node. See :ref:`raid`
    for more information. This step is part of the ``raid`` interface.
  ``delete_configuration``:
    Deletes RAID configuration on the node. See :ref:`raid`
    for more information. This step is part of the ``raid`` interface.
  ``update_firmware``:
    Updates the firmware of the devices. Also an out-of-band step associated
    with the ``management`` interface. See
    `Initiating firmware update as manual clean step`_ for user guidance on
    usage. The supported devices for firmware update are: ``ilo``, ``cpld``,
    ``power_pic``, ``bios`` and ``chassis``. Please refer to below table for
    their commonly used descriptions.

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
  ``update_firmware_sum``:
    Updates all or list of user specified firmware components on the node
    using Smart Update Manager (SUM). It is an inband step associated with
    the ``management`` interface. See `Smart Update Manager (SUM) based firmware update`_
    for more information on usage.

* iLO with firmware version 1.5 is minimally required to support all the
  operations.

For more information on node manual cleaning, see :ref:`manual_cleaning`

Node Deployment Customization
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
The hardware type ``ilo`` and ``ilo5`` supports customization of node
deployment via deploy templates, see :doc:`/admin/node-deployment`.

The supported deploy steps are:

* ``apply_configuration``:
    Applies given BIOS settings on the node. See
    `BIOS configuration support`_. This step is part of the ``bios`` interface.
* ``factory_reset``:
    Resets the BIOS settings on the node to factory defaults. See
    `BIOS configuration support`_. This step is part of the ``bios`` interface.
* ``reset_bios_to_default``:
    Resets system ROM settings to default. This step is supported only
    on Gen9 and above servers. This step is part of the ``management``
    interface.
* ``reset_secure_boot_keys_to_default``:
    Resets secure boot keys to manufacturer's defaults. This step is supported
    only on Gen9 and above servers. This step is part of the ``management``
    interface.
* ``reset_ilo_credential``:
    Resets the iLO password. The password need to be specified in
    ``ilo_password`` argument of the step. This step is part of the
    ``management`` interface.
* ``clear_secure_boot_keys``:
    Clears all secure boot keys. This step is supported only on Gen9 and above
    servers. This step is part of the ``management`` interface.
* ``reset_ilo``:
    Resets the iLO. This step is part of the ``management`` interface.
* ``update_firmware``:
    Updates the firmware of the devices. This step is part of the
    ``management`` interface. See
    `Initiating firmware update as manual clean step`_ for user guidance on
    usage. The supported devices for firmware update are: ``ilo``, ``cpld``,
    ``power_pic``, ``bios`` and ``chassis``. This step is part of
    ``management`` interface. Please refer to below table for their commonly
    used descriptions.

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

*  ``flash_firmware_sum``:
     Updates all or list of user specified firmware components on the node
     using Smart Update Manager (SUM). It is an inband step associated with
     the ``management`` interface. See `Smart Update Manager (SUM) based firmware update`_
     for more information on usage.
* ``apply_configuration``:
    Applies RAID configuration on the node. See :ref:`raid`
    for more information. This step is part of the ``raid`` interface.

Example of using deploy template with the Compute service
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Create a deploy template with a single step:

.. code-block:: console

   openstack baremetal deploy template create \
       CUSTOM_HYPERTHREADING_ON \
       --steps '[{"interface": "bios", "step": "apply_configuration", "args": {"settings": [{"name": "ProcHyperthreading", "value": "Enabled"}]}, "priority": 150}]'

Add the trait ``CUSTOM_HYPERTHREADING_ON`` to the node represented by ``$node_ident``:

.. code-block:: console

   openstack baremetal node add trait $node_ident CUSTOM_HYPERTHREADING_ON

Update the flavor ``bm-hyperthreading-on`` in the Compute service with the
following property:

.. code-block:: console

   openstack flavor set --property trait:CUSTOM_HYPERTHREADING_ON=required bm-hyperthreading-on

Creating a Compute instance with this flavor will ensure that the instance is
scheduled only to Bare Metal nodes with the ``CUSTOM_HYPERTHREADING_ON`` trait.
When an instance is created using the ``bm-hyperthreading-on`` flavor, then the
deploy steps of deploy template ``CUSTOM_HYPERTHREADING_ON`` will be executed
during the deployment of the scheduled node, causing Hyperthreading to be
enabled in the node's BIOS configuration.

.. _ilo-inspection:

Hardware Inspection Support
^^^^^^^^^^^^^^^^^^^^^^^^^^^
The hardware type ``ilo`` supports hardware inspection.

.. note::

   * The disk size is returned by RIBCL/RIS only when RAID is preconfigured
     on the storage. If the storage is Direct Attached Storage, then
     RIBCL/RIS fails to get the disk size.
   * The SNMPv3 inspection gets disk size for all types of storages.
     If RIBCL/RIS is unable to get disk size and SNMPv3 inspection is
     requested, the proliantutils does SNMPv3 inspection to get the
     disk size. If proliantutils is unable to get the disk size, it raises
     an error. This feature is available in proliantutils release
     version >= 2.2.0.
   * The iLO must be updated with SNMPv3 authentication details.
     Pleae refer to the section `SNMPv3 Authentication` in `HPE iLO4 User Guide`_
     for setting up authentication details on iLO.
     The  following parameters are mandatory to be given in driver_info
     for SNMPv3 inspection:

     * ``snmp_auth_user`` : The SNMPv3 user.

     * ``snmp_auth_prot_password`` : The auth protocol pass phrase.

     * ``snmp_auth_priv_password`` : The privacy protocol pass phrase.

     The  following parameters are optional for SNMPv3 inspection:

     * ``snmp_auth_protocol`` : The Auth Protocol. The valid values
       are "MD5" and "SHA". The iLO default value is "MD5".

     * ``snmp_auth_priv_protocol`` : The Privacy protocol. The valid
       values are "AES" and "DES". The iLO default value is "DES".

The inspection process will discover the following essential properties
(properties required for scheduling deployment):

* ``memory_mb``: memory size

* ``cpus``: number of cpus

* ``cpu_arch``: cpu architecture

* ``local_gb``: disk size

Inspection can also discover the following extra capabilities for iLO driver:

* ``ilo_firmware_version``: iLO firmware version

* ``rom_firmware_version``: ROM firmware version

* ``secure_boot``: secure boot is supported or not. The possible values are
  'true' or 'false'. The value is returned as 'true' if secure boot is supported
  by the server.

* ``server_model``: server model

* ``pci_gpu_devices``: number of gpu devices connected to the bare metal.

* ``nic_capacity``: the max speed of the embedded NIC adapter.

* ``sriov_enabled``: true, if server has the SRIOV supporting NIC.

* ``has_rotational``: true, if server has HDD disk.

* ``has_ssd``: true, if server has SSD disk.

* ``has_nvme_ssd``: true, if server has NVME SSD disk.

* ``cpu_vt``: true, if server supports cpu virtualization.

* ``hardware_supports_raid``: true, if RAID can be configured on the server using
  RAID controller.

* ``nvdimm_n``: true, if server has NVDIMM_N type of persistent memory.

* ``persistent_memory``: true, if server has persistent memory.

* ``logical_nvdimm_n``: true, if server has logical NVDIMM_N configured.

* ``rotational_drive_<speed>_rpm``: The capabilities
  ``rotational_drive_4800_rpm``, ``rotational_drive_5400_rpm``,
  ``rotational_drive_7200_rpm``, ``rotational_drive_10000_rpm`` and
  ``rotational_drive_15000_rpm`` are set to true if the server has HDD
  drives with speed of 4800, 5400, 7200, 10000 and 15000 rpm respectively.

* ``logical_raid_level_<raid_level>``: The capabilities
  ``logical_raid_level_0``, ``logical_raid_level_1``, ``logical_raid_level_2``,
  ``logical_raid_level_5``, ``logical_raid_level_6``, ``logical_raid_level_10``,
  ``logical_raid_level_50`` and ``logical_raid_level_60`` are set to true if any
  of the raid levels among 0, 1, 2, 5, 6, 10, 50 and 60 are configured on
  the system.

* ``overall_security_status``: ``Ok`` or ``Risk`` or ``Ignored`` as returned by iLO
  security dashboard.  iLO computes the overall security status by evaluating
  the security status for each of the security parameters. Admin needs to fix
  the actual parameters and then re-inspect so that iLO can recompute the
  overall security status. If the all security params, whose ``security_status`` is
  ``Risk``, have the ``Ignore`` field set to ``True``, then iLO sets
  the overall security status value as ``Ignored``. All the security params must have
  the ``security_status`` as ``Ok`` for the ``overall_security_status``
  to have the value as ``Ok``.

* ``last_firmware_scan_status``: ``Ok`` or ``Risk`` as returned by iLO security dashboard.
  This denotes security status of the last firmware scan done on the system. If it is
  ``Risk``, the recommendation is to run clean_step ``update_firmware_sum`` without any
  specific firmware components so that firmware is updated for all the components using
  latest SPP (Service Provider Pack) ISO and then re-inspect to get the security status
  again.

* ``security_override_switch``: ``Ok`` or ``Risk`` as returned by iLO security dashboard.
  This is disable/enable login to the iLO using credentials. This can be toggled only
  by physical visit to the bare metal.

  .. note::

     * The capability ``nic_capacity`` can only be discovered if ipmitool
       version >= 1.8.15 is used on the conductor. The latest version can be
       downloaded from `here <https://sourceforge.net/projects/ipmitool/>`__.
     * The iLO firmware version needs to be 2.10 or above for nic_capacity to be
       discovered.
     * To discover IPMI based attributes you need to enable iLO feature
       'IPMI/DCMI over LAN Access' on
       `iLO4 <https://support.hpe.com/hpsc/doc/public/display?docId=c03334051>`_
       and `iLO5 <https://support.hpe.com/hpsc/doc/public/display?docId=a00018324en_us>`_
       management engine.
     * The proliantutils returns only active NICs for Gen10 ProLiant HPE servers.
       The user would need to delete the ironic ports corresponding to inactive NICs
       for Gen8 and Gen9 servers as proliantutils returns all the discovered
       (active and otherwise) NICs for Gen8 and Gen9 servers and ironic ports
       are created for all of them. Inspection logs a warning if the node under
       inspection is Gen8 or Gen9.
     * The security dashboard capabilities are applicable only for Gen10 ProLiant HPE
       servers and above. To fix the security dashboard parameters value from
       ``Risk`` to ``Ok``, user need to fix the parameters separately and re-inspect
       to see the security status of the parameters.

The operator can specify these capabilities in nova flavor for node to be selected
for scheduling::

  nova flavor-key my-baremetal-flavor set capabilities:server_model="<in> Gen8"

  nova flavor-key my-baremetal-flavor set capabilities:nic_capacity="10Gb"

  nova flavor-key my-baremetal-flavor set capabilities:ilo_firmware_version="<in> 2.10"

  nova flavor-key my-baremetal-flavor set capabilities:has_ssd="true"

See :ref:`capabilities-discovery` for more details and examples.

Swiftless deploy for intermediate images
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

The hardware type ``ilo`` with ``ilo-virtual-media`` as boot interface
can deploy and boot the server with and without ``swift`` being used for
hosting the intermediate temporary floppy image (holding metadata for
deploy kernel and ramdisk) and the boot ISO. A local HTTP(S) web server on
each conductor node needs to be configured.
Please refer to `Web server configuration on conductor`_ for more information.
The HTTPS web server needs to be enabled (instead of HTTP web server) in order
to send management information and images in encrypted channel over HTTPS.

.. note::
    This feature assumes that the user inputs are on Glance which uses swift
    as backend. If swift dependency has to be eliminated, please refer to
    `HTTP(S) Based Deploy Support`_ also.

Deploy Process
~~~~~~~~~~~~~~

Please refer to `Netboot in swiftless deploy for intermediate images`_ for
partition image support and `Localboot in swiftless deploy for intermediate images`_
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

Please refer to `Netboot with HTTP(S) based deploy`_ for partition image boot
and `Localboot with HTTP(S) based deploy`_ for whole disk image boot.


Support for iLO driver with Standalone Ironic
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

It is possible to use ironic as standalone services without other
OpenStack services. The ``ilo`` hardware type can be used in standalone ironic.
This feature is referred to as ``iLO driver with standalone ironic`` in this document.

Configuration
~~~~~~~~~~~~~
The HTTP(S) web server needs to be configured as described in `HTTP(S) Based Deploy Support`_
and `Web server configuration on conductor`_ needs to be configured for hosting
intermediate images on conductor as described in
`Swiftless deploy for intermediate images`_.

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
iLO driver can activate the iLO Advanced license key as a manual cleaning
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
iLO driver can invoke secure firmware update as a manual cleaning step. Any
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
     ``service`` and the container is generally ``ironic`` and ``ilo`` driver
     uses a container named ``ironic_ilo_container`` for their own purpose.

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

Smart Update Manager (SUM) based firmware update
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

The firmware update based on `SUM`_ is an inband clean/deploy step supported
by iLO driver. The firmware update is performed on all or list of user
specified firmware components on the node. Refer to `SUM User Guide`_ to get
more information on SUM based firmware update.

.. note::
   ``update_firmware_sum`` clean step requires the agent ramdisk with
   ``Proliant Hardware Manager`` from the proliantutils version 2.5.0 or
   higher.  See `DIB support for Proliant Hardware Manager`_ to create the
   agent ramdisk with ``Proliant Hardware Manager``.

.. note::
   ``flash_firmware_sum`` deploy step requires the agent ramdisk with
   ``Proliant Hardware Manager`` from the proliantutils version 2.9.5 or
   higher.  See `DIB support for Proliant Hardware Manager`_ to create the
   agent ramdisk with ``Proliant Hardware Manager``.

The attributes of ``update_firmware_sum``/``flash_firmware_sum`` step are as
follows:

.. csv-table::
 :header: "Attribute", "Description"
 :widths: 30, 120

 "``interface``", "Interface of the clean step, here ``management``"
 "``step``", "Name of the clean step, here ``update_firmware_sum``"
 "``args``", "Keyword-argument entry (<name>: <value>) being passed to the clean step"

The keyword arguments used for the step are as follows:

* ``url``: URL of SPP (Service Pack for Proliant) ISO. It is mandatory. The
  URL schemes supported are ``http``, ``https`` and ``swift``.
* ``checksum``: MD5 checksum of SPP ISO to verify the image. It is mandatory.
* ``components``: List of filenames of the firmware components to be flashed.
  It is optional. If not provided, the firmware update is performed on all
  the firmware components.

The step performs an update on all or a list of firmware components and
returns the SUM log files. The log files include ``hpsum_log.txt`` and
``hpsum_detail_log.txt`` which holds the information about firmware components,
firmware version for each component and their update status. The log object
will be named with the following pattern::

    <node-uuid>[_<instance-uuid>]_update_firmware_sum_<timestamp yyyy-mm-dd-hh-mm-ss>.tar.gz
    or
    <node-uuid>[_<instance-uuid>]_flash_firmware_sum_<timestamp yyyy-mm-dd-hh-mm-ss>.tar.gz

Refer to :ref:`retrieve_deploy_ramdisk_logs` for more information on enabling and
viewing the logs returned from the ramdisk.

An example of ``update_firmware_sum`` clean step:

.. code-block:: json

    {
        "interface": "management",
        "step": "update_firmware_sum",
        "args":
            {
                "url": "http://my_address:port/SPP.iso",
                "checksum": "abcdefxyz",
                "components": ["CP024356.scexe", "CP008097.exe"]
            }
    }

The step fails if there is any error in the processing of step arguments.
The processing error could happen during validation of components'
file extension, image download, image checksum verification or image extraction.
In case of a failure, check Ironic conductor logs carefully to see if there are
any validation or firmware processing related errors which may help in root
cause analysis or gaining an understanding of where things were left off or
where things failed. You can then fix or work around and then try again.

.. warning::
   This feature is officially supported only with RHEL and SUSE based IPA ramdisk.
   Refer to `SUM`_ for supported OS versions for specific SUM version.

.. note::
   Refer `Guidelines for SPP ISO`_ for steps to get SPP (Service Pack for
   ProLiant) ISO.

RAID Support
^^^^^^^^^^^^

The inband RAID functionality is supported by iLO driver. See :ref:`raid`
for more information.
Bare Metal service update node with following information after successful
configuration of RAID:

* Node ``properties/local_gb`` is set to the size of root volume.
* Node ``properties/root_device`` is filled with ``wwn`` details of root
  volume. It is used by iLO driver as root device hint during provisioning.
* The value of raid level of root volume is added as ``raid_level`` capability
  to the node's ``capabilities`` parameter within ``properties`` field. The
  operator can specify the ``raid_level`` capability in nova flavor for node
  to be selected for scheduling::

    nova flavor-key ironic-test set capabilities:raid_level="1+0"
    nova boot --flavor ironic-test --image test-image instance-1

.. _DIB_raid_support:

DIB support for Proliant Hardware Manager
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

Install ``ironic-python-agent-builder`` following the guide [1]_

To create an agent ramdisk with ``Proliant Hardware Manager``,
use the ``proliant-tools`` element in DIB::

  ironic-python-agent-builder -o proliant-agent-ramdisk -e proliant-tools fedora

Disk Erase Support
^^^^^^^^^^^^^^^^^^

``erase_devices`` is an inband clean step supported by iLO driver. It
performs erase on all the disks including the disks visible to OS as
well as the raw disks visible to the Smart Storage Administrator (SSA).

This inband clean step requires ``ssacli`` utility starting from version
``2.60-19.0`` to perform the erase on physical disks. See the
`ssacli documentation`_ for more information on ssacli utility and different
erase methods supported by SSA.

The disk erasure via ``shred`` is used to erase disks visible to the OS
and its implementation is available in Ironic Python Agent. The raw disks
connected to the Smart Storage Controller are erased using Sanitize erase
which is a ssacli supported erase method. If Sanitize erase is not supported
on the Smart Storage Controller the disks are erased using One-pass
erase (overwrite with zeros).

This clean step is supported when the agent ramdisk contains the
``Proliant Hardware Manager`` from the proliantutils version 2.3.0 or higher.
This clean step is performed as part of automated cleaning and it is disabled
by default. See :ref:`InbandvsOutOfBandCleaning` for more information on
enabling/disabling a clean step.

Install ``ironic-python-agent-builder`` following the guide [1]_

To create an agent ramdisk with ``Proliant Hardware Manager``, use the
``proliant-tools`` element in DIB::

    ironic-python-agent-builder -o proliant-agent-ramdisk -e proliant-tools fedora

See the `proliant-tools`_ for more information on creating agent ramdisk with
``proliant-tools`` element in DIB.

Firmware based UEFI iSCSI boot from volume support
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
With Gen9 (UEFI firmware version 1.40 or higher) and Gen10 HPE Proliant
servers, the driver supports firmware based UEFI boot of an iSCSI cinder volume.

This feature requires the node to be configured to boot in ``UEFI`` boot mode,
as well as user image should be ``UEFI`` bootable image, and ``PortFast``
needs to be enabled in switch configuration for immediate spanning tree
forwarding state so it wouldn't take much time setting the iSCSI target as
persistent device.

The driver does not support this functionality when in ``bios`` boot mode. In
case the node is configured with ``ilo-pxe`` or ``ilo-ipxe`` as boot interface
and the boot mode configured on the bare metal is ``bios``, the iscsi boot
from volume is performed using iPXE. See :doc:`/admin/boot-from-volume`
for more details.

To use this feature, configure the boot mode of the bare metal to ``uefi`` and
configure the corresponding ironic node using the steps given in :doc:`/admin/boot-from-volume`.
In a cloud environment with nodes configured to boot from ``bios`` and ``uefi`` boot
modes, the virtual media driver only supports uefi boot mode, and that attempting to
use iscsi boot at the same time with a bios volume will result in an error.

BIOS configuration support
^^^^^^^^^^^^^^^^^^^^^^^^^^
The ``ilo`` and ``ilo5`` hardware types support ``ilo`` BIOS interface.
The support includes providing manual clean steps *apply_configuration* and
*factory_reset* to manage supported BIOS settings on the node.
See :ref:`bios` for more details and examples.

.. note::
   Prior to the Stein release the user is required to reboot the node manually
   in order for the settings to take into effect. Starting with the Stein
   release, iLO drivers reboot the node after running clean steps related to
   the BIOS configuration. The BIOS settings are cached and the clean step is
   marked as success only if all the requested settings are applied without
   any failure. If application of any of the settings fails, the clean step is
   marked as failed and the settings are not cached.

Configuration
~~~~~~~~~~~~~
Following are the supported BIOS settings and the corresponding brief
description for each of the settings. For a detailed description please
refer to `HPE Integrated Lights-Out REST API Documentation <https://hewlettpackard.github.io/ilo-rest-api-docs>`_.

- ``AdvancedMemProtection``:
  Configure additional memory protection with ECC (Error Checking and
  Correcting).
  Allowed values are ``AdvancedEcc``, ``OnlineSpareAdvancedEcc``,
  ``MirroredAdvancedEcc``.

- ``AutoPowerOn``:
  Configure the server to automatically power on when AC power is applied to
  the system.
  Allowed values are ``AlwaysPowerOn``, ``AlwaysPowerOff``,
  ``RestoreLastState``.

- ``BootMode``:
  Select the boot mode of the system.
  Allowed values are ``Uefi``, ``LegacyBios``

- ``BootOrderPolicy``:
  Configure how the system attempts to boot devices per the Boot Order when
  no bootable device is found.
  Allowed values are ``RetryIndefinitely``, ``AttemptOnce``,
  ``ResetAfterFailed``.

- ``CollabPowerControl``:
  Enables the Operating System to request processor frequency changes even
  if the Power Regulator option on the server configured for Dynamic Power
  Savings Mode.
  Allowed values are ``Enabled``, ``Disabled``.

- ``DynamicPowerCapping``:
  Configure when the System ROM executes power calibration during the boot
  process.
  Allowed values are ``Enabled``, ``Disabled``, ``Auto``.

- ``DynamicPowerResponse``:
  Enable the System BIOS to control processor performance and power states
  depending on the processor workload.
  Allowed values are ``Fast``, ``Slow``.

- ``IntelligentProvisioning``:
  Enable or disable the Intelligent Provisioning functionality.
  Allowed values are ``Enabled``, ``Disabled``.

- ``IntelPerfMonitoring``:
  Exposes certain chipset devices that can be used with the Intel
  Performance Monitoring Toolkit.
  Allowed values are ``Enabled``, ``Disabled``.

- ``IntelProcVtd``:
  Hypervisor or operating system supporting this option can use hardware
  capabilities provided by Intel's Virtualization Technology for Directed
  I/O.
  Allowed values are ``Enabled``, ``Disabled``.

- ``IntelQpiFreq``:
  Set the QPI Link frequency to a lower speed.
  Allowed values are ``Auto``, ``MinQpiSpeed``.

- ``IntelTxt``:
  Option to modify Intel TXT support.
  Allowed values are ``Enabled``, ``Disabled``.

- ``PowerProfile``:
  Set the power profile to be used.
  Allowed values are ``BalancedPowerPerf``, ``MinPower``, ``MaxPerf``,
  ``Custom``.

- ``PowerRegulator``:
  Determines how to regulate the power consumption.
  Allowed values are ``DynamicPowerSavings``, ``StaticLowPower``,
  ``StaticHighPerf``, ``OsControl``.

- ``ProcAes``:
  Enable or disable the Advanced Encryption Standard Instruction Set
  (AES-NI) in the processor.
  Allowed values are ``Enabled``, ``Disabled``.

- ``ProcCoreDisable``:
  Disable processor cores using Intel's Core Multi-Processing (CMP)
  Technology.
  Allowed values are Integers ranging from ``0`` to ``24``.

- ``ProcHyperthreading``:
  Enable or disable Intel Hyperthreading.
  Allowed values are ``Enabled``, ``Disabled``.

- ``ProcNoExecute``:
  Protect your system against malicious code and viruses.
  Allowed values are ``Enabled``, ``Disabled``.

- ``ProcTurbo``:
  Enables the processor to transition to a higher frequency than the
  processor's rated speed using Turbo Boost Technology if the processor
  has available power and is within temperature specifications.
  Allowed values are ``Enabled``, ``Disabled``.

- ``ProcVirtualization``:
  Enables or Disables a hypervisor or operating system supporting this option
  to use hardware capabilities provided by Intel's Virtualization Technology.
  Allowed values are ``Enabled``, ``Disabled``.

- ``SecureBootStatus``:
  The current state of Secure Boot configuration.
  Allowed values are ``Enabled``, ``Disabled``.

  .. note::
     This setting is read-only and can't be modified with ``apply_configuration``
     clean step.

- ``Sriov``:
  If enabled, SR-IOV support enables a hypervisor to create virtual instances
  of a PCI-express device, potentially increasing performance. If enabled,
  the BIOS allocates additional resources to PCI-express devices.
  Allowed values are ``Enabled``, ``Disabled``.

- ``ThermalConfig``:
  select the fan cooling solution for the system.
  Allowed values are ``OptimalCooling``, ``IncreasedCooling``,
  ``MaxCooling``

- ``ThermalShutdown``:
  Control the reaction of the system to caution level thermal events.
  Allowed values are ``Enabled``, ``Disabled``.

- ``TpmState``:
  Current TPM device state.
  Allowed values are ``NotPresent``, ``PresentDisabled``, ``PresentEnabled``.

  .. note::
     This setting is read-only and can't be modified with ``apply_configuration``
     clean step.

- ``TpmType``:
  Current TPM device type.
  Allowed values are ``NoTpm``, ``Tpm12``, ``Tpm20``, ``Tm10``.

  .. note::
     This setting is read-only and can't be modified with ``apply_configuration``
     clean step.

- ``UefiOptimizedBoot``:
  Enables or Disables the System BIOS boot using native UEFI graphics
  drivers.
  Allowed values are ``Enabled``, ``Disabled``.

- ``WorkloadProfile``:
  Change the Workload Profile to accomodate your desired workload.
  Allowed values are ``GeneralPowerEfficientCompute``,
  ``GeneralPeakFrequencyCompute``, ``GeneralThroughputCompute``,
  ``Virtualization-PowerEfficient``, ``Virtualization-MaxPerformance``,
  ``LowLatency``, ``MissionCritical``,
  ``TransactionalApplicationProcessing``, ``HighPerformanceCompute``,
  ``DecisionSupport``, ``GraphicProcessing``, ``I/OThroughput``, ``Custom``

  .. note::
     This setting is only applicable to ProLiant Gen10 servers with iLO 5
     management systems.

Certificate based validation in iLO
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
The driver supports validation of certificates on the HPE Proliant servers.
The path to certificate file needs to be appropriately set in ``ca_file`` in
the node's ``driver_info``. To update SSL certificates into iLO,
refer to `HPE Integrated Lights-Out Security Technology Brief <http://h20564.www2.hpe.com/hpsc/doc/public/display?docId=c04530504>`_.
Use iLO hostname or IP address as a 'Common Name (CN)' while
generating Certificate Signing Request (CSR). Use the same value as
`ilo_address` while enrolling node to Bare Metal service to avoid SSL
certificate validation errors related to hostname mismatch.

Rescue mode support
^^^^^^^^^^^^^^^^^^^
The hardware type ``ilo`` supports rescue functionality. Rescue operation can
be used to boot nodes into a rescue ramdisk so that the ``rescue`` user can
access the node.

Please refer to :doc:`/admin/rescue` for detailed explanation of rescue
feature.

Inject NMI support
^^^^^^^^^^^^^^^^^^
The management interface ``ilo`` supports injection of non-maskable
interrupt (NMI) to a bare metal. Following command can be used to inject
NMI on a server:

.. code-block:: console

    openstack baremetal node inject nmi <node>

Following command can be used to inject NMI via Compute service:

.. code-block:: console

    openstack server dump create <server>

.. note::
   This feature is supported on HPE ProLiant Gen9 servers and beyond.

Soft power operation support
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
The power interface ``ilo`` supports soft power off and soft reboot
operations on a bare metal. Following commands can be used to perform
soft power operations on a server:

.. code-block:: console

    openstack baremetal node reboot --soft \
        [--power-timeout <power-timeout>] <node>

    openstack baremetal node power off --soft \
        [--power-timeout <power-timeout>] <node>

.. note::
   The configuration ``[conductor]soft_power_off_timeout`` is used as a
   default timeout value when no timeout is provided while invoking
   hard or soft power operations.

.. note::
   Server POST state is used to track the power status of HPE ProLiant Gen9
   servers and beyond.

Out of Band RAID Support
^^^^^^^^^^^^^^^^^^^^^^^^
With Gen10 HPE Proliant servers and later the ``ilo5`` hardware type supports
firmware based RAID configuration as a clean step. This feature requires the
node to be configured to ``ilo5`` hardware type and its raid interface to be
``ilo5``. See :ref:`raid` for more information.

After a successful RAID configuration, the Bare Metal service will update the
node with the following information:

* Node ``properties/local_gb`` is set to the size of root volume.
* Node ``properties/root_device`` is filled with ``wwn`` details of root
  volume. It is used by iLO driver as root device hint during provisioning.

Later the value of raid level of root volume can be added in
``baremetal-with-RAID10`` (RAID10 for raid level 10) resource class.
And consequently flavor needs to be updated to request the resource class
to create the server using selected node::

    openstack baremetal node set test_node --resource-class \
    baremetal-with-RAID10

    openstack flavor set --property \
    resources:CUSTOM_BAREMETAL_WITH_RAID10=1 test-flavor

    openstack server create --flavor test-flavor --image test-image instance-1


.. note::
   Supported raid levels for ``ilo5`` hardware type are: 0, 1, 5, 6, 10, 50, 60

IPv6 support
^^^^^^^^^^^^
With the IPv6 support in ``proliantutils>=2.8.0``, nodes can be enrolled
into the baremetal service using the iLO IPv6 addresses.

.. code-block:: console

    openstack baremetal node create --driver ilo  --deploy-interface direct \
        --driver-info ilo_address=2001:0db8:85a3:0000:0000:8a2e:0370:7334 \
        --driver-info ilo_username=test-user \
        --driver-info ilo_password=test-password \
        --driver-info ilo_deploy_iso=test-iso \
        --driver-info ilo_rescue_iso=test-iso


.. note::
   No configuration changes (in e.g. ironic.conf) are required in order to
   support IPv6.

Out of Band Sanitize Disk Erase Support
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
With Gen10 HPE Proliant servers and later the ``ilo5`` hardware type supports
firmware based sanitize disk erase as a clean step. This feature requires the
node to be configured to ``ilo5`` hardware type and its management interface
to be ``ilo5``.

The possible erase pattern its supports are:

* For HDD - 'overwrite', 'zero', 'crypto'
* For SSD - 'block', 'zero', 'crypto'

The default erase pattern are, for HDD, 'overwrite' and for SSD, 'block'.


.. note::
   In average 300GB HDD with default pattern "overwrite" would take approx.
   9 hours and 300GB SSD with default pattern "block" would take approx. 30
   seconds to complete the erase.

Out of Band One Button Secure Erase Support
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
With Gen10 HPE Proliant servers which have been updated with SPP version 2019.03.0
or later the ``ilo5`` hardware type supports firmware based one button secure erase
as a clean step.

The One Button Secure Erase resets iLO and deletes all licenses stored there, resets
BIOS settings, and deletes all Active Health System (AHS) and warranty data stored on
the system. It also erases supported non-volatile storage data and deletes any
deployment settings profiles. See `HPE Gen10 Security Reference Guide`_ for more
information.

Below are the steps to perform this clean step:

* Perform the cleaning using 'one_button_secure_erase' clean step

.. code-block:: console

    openstack baremetal node clean test_node --clean-steps\
        '[{"interface": "management", "step": "one_button_secure_erase"}]'

* Once the clean step would triggered and node go to 'clean wait' state and
  'maintenance' flag on node would be set to 'True', then delete the node

.. code-block:: console

    openstack baremetal node delete test_node

.. note::
   * Even after deleting the node, One Button Secure Erase operation would continue
     on the node.

   * This clean step should be kept last if the multiple clean steps are to be executed.
     No clean step after this step would be executed.

   * One Button Secure Erase should be used with extreme caution, and only when a system
     is being decommissioned. During the erase the iLO network would keep disconnecting
     and after the erase user will completly lose iLO access along with the credentials
     of the server, which needs to be regained by the administrator. The process can take
     up to a day or two to fully erase and reset all user data.

   * When you activate One Button Secure Erase, iLO 5 does not allow firmware update
     or reset operations.

.. note::
   Do not perform any iLO 5 configuration changes until this process is completed.

UEFI-HTTPS Boot support
^^^^^^^^^^^^^^^^^^^^^^^
The UEFI firmware on Gen10 HPE Proliant servers supports booting from secured URLs.
With this capability ``ilo5`` hardware with ``ilo-uefi-https`` boot interface supports
deploy/rescue features in more secured environments.

If swift is used as glance backend and ironic is configured to use swift to store
temporary images, it is required that swift is configured on HTTPS so that the tempurl
generated is HTTPS URL.

If the webserver is used for hosting the temporary images, then the webserver is required
to serve requests on HTTPS.

If the images are hosted on a HTTPS webserver or swift configured with HTTPS with
custom certificates, the user is required to export SSL certificates into iLO.
Refer to `HPE Integrated Lights-Out Security Technology Brief`_ for more information.

The following command can be used to enroll a ProLiant node with ``ilo5`` hardware type
and ``ilo-uefi-https`` boot interface:

.. code-block:: console

    openstack baremetal node create \
        --driver ilo5 \
        --boot-interface ilo-uefi-https \
        --deploy-interface direct \
        --raid-interface ilo5 \
        --rescue-interface agent \
        --driver-info ilo_address=<ilo-ip-address> \
        --driver-info ilo_username=<ilo-username> \
        --driver-info ilo_password=<ilo-password> \
        --driver-info ilo_deploy_kernel=<glance-uuid-of-deploy-kernel> \
        --driver-info ilo_deploy_ramdisk=<glance-uuid-of-rescue-ramdisk> \
        --driver-info ilo_bootloader=<glance-uuid-of-bootloader>

.. note::
   UEFI secure boot is not supported with ``ilo-uefi-https`` boot interface.


.. _`ssacli documentation`: https://support.hpe.com/hpsc/doc/public/display?docId=c03909334
.. _`proliant-tools`: https://docs.openstack.org/diskimage-builder/latest/elements/proliant-tools/README.html
.. _`HPE iLO4 User Guide`: https://h20566.www2.hpe.com/hpsc/doc/public/display?docId=c03334051
.. _`HPE Gen10 Security Reference Guide`: https://support.hpe.com/hpesc/public/docDisplay?docLocale=en_US&docId=a00018320en_us
.. _`iLO 4 management engine`: https://www.hpe.com/us/en/servers/integrated-lights-out-ilo.html
.. _`iLO 5 management engine`: https://www.hpe.com/us/en/servers/integrated-lights-out-ilo.html#innovations
.. _`Redfish`: https://www.dmtf.org/standards/redfish
.. _`Gen10 wiki section`: https://wiki.openstack.org/wiki/Ironic/Drivers/iLODrivers/master#Enabling_ProLiant_Gen10_systems_in_Ironic
.. _`Guidelines for SPP ISO`: https://h17007.www1.hpe.com/us/en/enterprise/servers/products/service_pack/spp
.. _`SUM`: https://h17007.www1.hpe.com/us/en/enterprise/servers/products/service_pack/hpsum/index.aspx
.. _`SUM User Guide`: https://h20565.www2.hpe.com/hpsc/doc/public/display?docId=c05210448
.. [1] `ironic-python-agent-builder`: https://docs.openstack.org/ironic-python-agent-builder/latest/install/index.html
.. _`HPE Integrated Lights-Out Security Technology Brief`: http://h20564.www2.hpe.com/hpsc/doc/public/display?docId=c04530504
