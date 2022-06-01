.. _irmc:

===========
iRMC driver
===========

Overview
========

The iRMC driver enables control FUJITSU PRIMERGY via ServerView
Common Command Interface (SCCI). Support for FUJITSU PRIMERGY servers consists
of the ``irmc`` hardware type and a few hardware interfaces specific for that
hardware type.

Prerequisites
=============

* Install `python-scciclient <https://pypi.org/project/python-scciclient>`_
  and `pysnmp <https://pypi.org/project/pysnmp>`_ packages::

  $ pip install "python-scciclient>=0.7.2" pysnmp

Hardware Type
=============

The ``irmc`` hardware type is available for FUJITSU PRIMERGY servers. For
information on how to enable the ``irmc`` hardware type, see
:ref:`enable-hardware-types`.

Hardware interfaces
^^^^^^^^^^^^^^^^^^^

The ``irmc`` hardware type overrides the selection of the following
hardware interfaces:

* bios
    Supports  ``irmc`` and ``no-bios``.
    The default is ``irmc``.

* boot
    Supports ``irmc-virtual-media``, ``irmc-pxe``, and ``pxe``.
    The default is ``irmc-virtual-media``. The ``irmc-virtual-media`` boot
    interface enables the virtual media based deploy with IPA (Ironic Python
    Agent).

    .. warning::
       We deprecated the ``pxe`` boot interface when used with ``irmc``
       hardware type. Support for this interface will be removed in the
       future. Instead, use ``irmc-pxe``. ``irmc-pxe`` boot interface
       was introduced in Pike.

* console
    Supports ``ipmitool-socat``, ``ipmitool-shellinabox``, and ``no-console``.
    The default is ``ipmitool-socat``.

* inspect
    Supports ``irmc``, ``inspector``, and ``no-inspect``.
    The default is ``irmc``.

    .. note::
       :ironic-inspector-doc:`Ironic Inspector <>`
       needs to be present and configured to use ``inspector`` as the
       inspect interface.

* management
    Supports only ``irmc``.

* power
    Supports ``irmc``, which enables power control via ServerView Common
    Command Interface (SCCI), by default. Also supports ``ipmitool``.

* raid
    Supports  ``irmc``, ``no-raid`` and ``agent``.
    The default is ``no-raid``.

For other hardware interfaces, ``irmc`` hardware type supports the
Bare Metal reference interfaces. For more details about the hardware
interfaces and how to enable the desired ones, see
:ref:`enable-hardware-interfaces`.

Here is a complete configuration example with most of the supported hardware
interfaces enabled for ``irmc`` hardware type.

.. code-block:: ini

   [DEFAULT]
   enabled_hardware_types = irmc
   enabled_bios_interfaces = irmc
   enabled_boot_interfaces = irmc-virtual-media,irmc-pxe
   enabled_console_interfaces = ipmitool-socat,ipmitool-shellinabox,no-console
   enabled_deploy_interfaces = direct
   enabled_inspect_interfaces = irmc,inspector,no-inspect
   enabled_management_interfaces = irmc
   enabled_network_interfaces = flat,neutron
   enabled_power_interfaces = irmc
   enabled_raid_interfaces = no-raid,irmc
   enabled_storage_interfaces = noop,cinder
   enabled_vendor_interfaces = no-vendor,ipmitool

Here is a command example to enroll a node with ``irmc`` hardware type.

.. code-block:: console

   baremetal node create \
      --bios-interface irmc \
      --boot-interface irmc-pxe \
      --deploy-interface direct \
      --inspect-interface irmc  \
      --raid-interface irmc

Node configuration
^^^^^^^^^^^^^^^^^^

Configuration via ``driver_info``
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

* Each node is configured for ``irmc`` hardware type by setting the following
  ironic node object's properties:

  - ``driver_info/irmc_address`` property to be ``IP address`` or
    ``hostname`` of the iRMC.
  - ``driver_info/irmc_username`` property to be ``username`` for
    the iRMC with administrator privileges.
  - ``driver_info/irmc_password`` property to be ``password`` for
    irmc_username.
  - ``properties/capabilities`` property to be ``boot_mode:uefi`` if
    UEFI boot is required.
  - ``properties/capabilities`` property to be ``secure_boot:true`` if
    UEFI Secure Boot is required. Please refer to `UEFI Secure Boot Support`_
    for more information.

* If ``port`` in ``[irmc]`` section of ``/etc/ironic/ironic.conf`` or
  ``driver_info/irmc_port`` is set to 443, ``driver_info/irmc_verify_ca``
  will take effect:

  ``driver_info/irmc_verify_ca`` property takes one of 4 value (default value
  is ``True``):

  - ``True``: When set to ``True``, which certification file iRMC driver uses
    is determined by ``requests`` Python module.

    Value of ``driver_info/irmc_verify_ca`` is passed to ``verify`` argument
    of functions defined in ``requests`` Python module. So which certification
    will be used is depend on behavior of ``requests`` module.
    (maybe certification provided by ``certifi`` Python module)

  - ``False``: When set to ``False``, iRMC driver won't verify server
    certification with certification file during HTTPS connection with iRMC.
    Just stop to verify server certification, but does HTTPS.

    .. warning::
       When set to ``False``, user must notice that it can result in
       vulnerable situation. Stopping verification of server certification
       during HTTPS connection means it cannot prevent Man-in-the-middle
       attack. When set to ``False``, Ironic user must take enough care
       around infrastructure environment in terms of security.
       (e.g. make sure network between Ironic conductor and iRMC is secure)

  - string representing filesystem path to directory which contains
    certification file:  In this case, iRMC driver uses certification file
    stored at specified directory. Ironic conductor must be able to access
    that directory. For iRMC to recongnize certification file, Ironic user
    must run ``openssl rehash <path_to_dir>``.

  - string representing filesystem path to certification file: In this case,
    iRMC driver uses certification file specified. Ironic conductor must have
    access to that file.


* The following properties are also required if ``irmc-virtual-media`` boot
  interface is used:

  - ``driver_info/deploy_iso`` property to be either deploy iso
    file name, Glance UUID, or Image Service URL.
  - ``instance info/boot_iso`` property to be either boot iso
    file name, Glance UUID, or Image Service URL. This is optional
    property when ``boot_option`` is set to ``netboot``.

  .. note::
     The ``deploy_iso`` and ``boot_iso`` properties used to be called
     ``irmc_deploy_iso`` and ``irmc_boot_iso`` accordingly before the Xena
     release.


Configuration via ``ironic.conf``
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

* All of the nodes are configured by setting the following configuration
  options in the ``[irmc]`` section of ``/etc/ironic/ironic.conf``:

  - ``port``: Port to be used for iRMC operations; either 80
    or 443. The default value is 443. Optional.
  - ``auth_method``: Authentication method for iRMC operations;
    either ``basic`` or ``digest``. The default value is ``basic``. Optional.
  - ``client_timeout``: Timeout (in seconds) for iRMC
    operations. The default value is 60. Optional.
  - ``sensor_method``: Sensor data retrieval method; either
    ``ipmitool`` or ``scci``. The default value is ``ipmitool``. Optional.

* The following options are required if ``irmc-virtual-media`` boot
  interface is enabled:

  - ``remote_image_share_root``: Ironic conductor node's ``NFS`` or
    ``CIFS`` root path. The default value is ``/remote_image_share_root``.
  - ``remote_image_server``: IP of remote image server.
  - ``remote_image_share_type``: Share type of virtual media, either
    ``NFS`` or ``CIFS``. The default is ``CIFS``.
  - ``remote_image_share_name``: share name of ``remote_image_server``.
    The default value is ``share``.
  - ``remote_image_user_name``: User name of ``remote_image_server``.
  - ``remote_image_user_password``: Password of ``remote_image_user_name``.
  - ``remote_image_user_domain``: Domain name of ``remote_image_user_name``.

* The following options are required if ``irmc`` inspect interface is enabled:

  - ``snmp_version``: SNMP protocol version; either ``v1``, ``v2c`` or
    ``v3``. The default value is ``v2c``. Optional.
  - ``snmp_port``: SNMP port. The default value is ``161``. Optional.
  - ``snmp_community``: SNMP community required for versions ``v1``
    and ``v2c``. The default value is ``public``. Optional.
  - ``snmp_security``: SNMP security name required for version ``v3``.
    Optional.


Override ``ironic.conf`` configuration via ``driver_info``
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

* Each node can be further configured by setting the following ironic
  node object's properties which override the parameter values in
  ``[irmc]`` section of ``/etc/ironic/ironic.conf``:

  - ``driver_info/irmc_port`` property overrides ``port``.
  - ``driver_info/irmc_auth_method`` property overrides ``auth_method``.
  - ``driver_info/irmc_client_timeout`` property overrides ``client_timeout``.
  - ``driver_info/irmc_sensor_method`` property overrides ``sensor_method``.
  - ``driver_info/irmc_snmp_version`` property overrides ``snmp_version``.
  - ``driver_info/irmc_snmp_port`` property overrides ``snmp_port``.
  - ``driver_info/irmc_snmp_community`` property overrides ``snmp_community``.
  - ``driver_info/irmc_snmp_security`` property overrides ``snmp_security``.


Optional functionalities for the ``irmc`` hardware type
=======================================================

UEFI Secure Boot Support
^^^^^^^^^^^^^^^^^^^^^^^^
The hardware type ``irmc`` supports secure boot deploy, see :ref:`secure-boot`
for details.

.. warning::
     Secure boot feature is not supported with ``pxe`` boot interface.

.. _irmc_node_cleaning:

Node Cleaning Support
^^^^^^^^^^^^^^^^^^^^^
The ``irmc`` hardware type supports node cleaning.
For more information on node cleaning, see :ref:`cleaning`.

Supported **Automated** Cleaning Operations
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

The automated cleaning operations supported are:

* ``restore_irmc_bios_config``:
  Restores BIOS settings on a baremetal node from backup data. If this
  clean step is enabled, the BIOS settings of a baremetal node will be
  backed up automatically before the deployment. By default, this clean
  step is disabled with priority ``0``. Set its priority to a positive
  integer to enable it. The recommended value is ``10``.

  .. warning::
     ``pxe`` boot interface, when used with ``irmc`` hardware type, does
     not support this clean step. If uses ``irmc`` hardware type, it is
     required to select ``irmc-pxe`` or ``irmc-virtual-media`` as the
     boot interface in order to make this clean step work.


Configuration options for the automated cleaning steps are listed under
``[irmc]`` section in ironic.conf ::

  clean_priority_restore_irmc_bios_config = 0

For more information on node automated cleaning, see :ref:`automated_cleaning`

Boot from Remote Volume
^^^^^^^^^^^^^^^^^^^^^^^
The ``irmc`` hardware type supports the generic iPXE-based remote volume
booting when using the following boot interfaces:

* ``irmc-pxe``
* ``pxe``

In addition, the ``irmc`` hardware type supports remote volume booting without
iPXE. This is available when using the ``irmc-virtual-media`` boot interface.
This feature configures a node to boot from a remote volume by using the API
of iRMC. It supports iSCSI and FibreChannel.

Configuration
~~~~~~~~~~~~~

In addition to the configuration for generic drivers to
:ref:`remote volume boot <boot-from-volume>`,
the iRMC driver requires the following configuration:

* It is necessary to set physical port IDs to network ports and volume
  connectors. All cards including those not used for volume boot should be
  registered.

  The format of a physical port ID is: ``<Card Type><Slot No>-<Port No>`` where:

  - ``<Card Type>``: could be ``LAN``, ``FC`` or ``CNA``
  - ``<Slot No>``: 0 indicates onboard slot. Use 1 to 9 for add-on slots.
  - ``<Port No>``: A port number starting from 1.

  These IDs are specified in a node's ``driver_info[irmc_pci_physical_ids]``.
  This value is a dictionary. The key is the UUID of a resource (Port or Volume
  Connector) and its value is the physical port ID. For example::

    {
      "1ecd14ee-c191-4007-8413-16bb5d5a73a2":"LAN0-1",
      "87f6c778-e60e-4df2-bdad-2605d53e6fc0":"CNA1-1"
    }

  It can be set with the following command::

      baremetal node set $NODE_UUID \
      --driver-info irmc_pci_physical_ids={} \
      --driver-info irmc_pci_physical_ids/$PORT_UUID=LAN0-1 \
      --driver-info irmc_pci_physical_ids/$VOLUME_CONNECTOR_UUID=CNA1-1

* For iSCSI boot, volume connectors with both types ``iqn`` and ``ip`` are
  required. The configuration with DHCP is not supported yet.

* For iSCSI, the size of the storage network is needed. This value should be
  specified in a node's ``driver_info[irmc_storage_network_size]``. It must be
  a positive integer < 32.
  For example, if the storage network is 10.2.0.0/22, use the following
  command::

    baremetal node set $NODE_UUID --driver-info irmc_storage_network_size=22

Supported hardware
~~~~~~~~~~~~~~~~~~

The driver supports the PCI controllers, Fibrechannel Cards, Converged Network
Adapters supported by
`Fujitsu ServerView Virtual-IO Manager <http://www.fujitsu.com/fts/products/computing/servers/primergy/management/primergy-blade-server-io-virtualization.html>`_.

Hardware Inspection Support
^^^^^^^^^^^^^^^^^^^^^^^^^^^

The ``irmc`` hardware type provides the iRMC-specific hardware inspection
with ``irmc`` inspect interface.

.. note::
   SNMP requires being enabled in ServerView® iRMC S4 Web Server(Network
   Settings\SNMP section).

Configuration
~~~~~~~~~~~~~

The Hardware Inspection Support in the iRMC driver requires the following
configuration:

* It is necessary to set ironic configuration with ``gpu_ids`` and
  ``fpga_ids`` options in ``[irmc]`` section.

  ``gpu_ids`` and ``fpga_ids`` are lists of ``<vendorID>/<deviceID>`` where:

  - ``<vendorID>``: 4 hexadecimal digits starts with '0x'.
  - ``<deviceID>``: 4 hexadecimal digits starts with '0x'.

  Here are sample values for ``gpu_ids`` and ``fpga_ids``::

    gpu_ids = 0x1000/0x0079,0x2100/0x0080
    fpga_ids = 0x1000/0x005b,0x1100/0x0180

* The python-scciclient package requires pyghmi version >= 1.0.22 and pysnmp
  version >= 4.2.3. They are used by the conductor service on the conductor.
  The latest version of pyghmi can be downloaded from `here
  <https://pypi.org/project/pyghmi/>`__
  and pysnmp can be downloaded from `here
  <https://pypi.org/project/pysnmp/>`__.

Supported properties
~~~~~~~~~~~~~~~~~~~~

The inspection process will discover the following essential properties
(properties required for scheduling deployment):

* ``memory_mb``: memory size

* ``cpus``: number of cpus

* ``cpu_arch``: cpu architecture

* ``local_gb``: disk size

Inspection can also discover the following extra capabilities for iRMC
driver:

* ``irmc_firmware_version``: iRMC firmware version

* ``rom_firmware_version``: ROM firmware version

* ``trusted_boot``: The flag whether TPM(Trusted Platform Module) is
  supported by the server. The possible values are 'True' or 'False'.

* ``server_model``: server model

* ``pci_gpu_devices``: number of gpu devices connected to the bare metal.

Inspection can also set/unset node's traits with the following cpu type for
iRMC driver:

* ``CUSTOM_CPU_FPGA``: The bare metal contains fpga cpu type.

.. note::

   * The disk size is returned only when eLCM License for FUJITSU PRIMERGY
     servers is activated. If the license is not activated, then Hardware
     Inspection will fail to get this value.
   * Before inspecting, if the server is power-off, it will be turned on
     automatically. System will wait for a few second before start
     inspecting. After inspection, power status will be restored to the
     previous state.

The operator can specify these capabilities in compute service flavor, for
example::

  openstack flavor set baremetal-flavor-name --property capabilities:irmc_firmware_version="iRMC S4-8.64F"

  openstack flavor set baremetal-flavor-name --property capabilities:server_model="TX2540M1F5"

  openstack flavor set baremetal-flavor-name --property capabilities:pci_gpu_devices="1"

See :ref:`capabilities-discovery` for more details and examples.

The operator can add a trait in compute service flavor, for example::

  baremetal node add trait $NODE_UUID CUSTOM_CPU_FPGA

A valid trait must be no longer than 255 characters. Standard traits are
defined in the os_traits library. A custom trait must start with the prefix
``CUSTOM_`` and use the following characters: A-Z, 0-9 and _.

RAID configuration Support
^^^^^^^^^^^^^^^^^^^^^^^^^^

The ``irmc`` hardware type provides the iRMC RAID configuration with ``irmc``
raid interface.

.. note::

   * RAID implementation for ``irmc`` hardware type is based on eLCM license
     and SDCard. Otherwise, SP(Service Platform) in lifecycle management
     must be available.
   * RAID implementation only supported for RAIDAdapter 0 in Fujitsu Servers.

Configuration
~~~~~~~~~~~~~

The RAID configuration Support in the iRMC drivers requires the following
configuration:

* It is necessary to set ironic configuration into Node with
  JSON file option::

    $ baremetal node set <node-uuid-or-name> \
      --target-raid-config <JSON file containing target RAID configuration>

  Here is some sample values for JSON file::

    {
        "logical_disks": [
            {
                "size_gb": 1000,
                "raid_level": "1"
        ]
    }

  or::

    {
        "logical_disks": [
            {
                "size_gb": 1000,
                "raid_level": "1",
                "controller": "FTS RAID Ctrl SAS 6G 1GB (D3116C) (0)",
                "physical_disks": [
                    "0",
                    "1"
                ]
            }
        ]
    }

.. note::

    RAID 1+0 and 5+0 in iRMC driver does not support property ``physical_disks``
    in ``target_raid_config`` during create raid configuration yet. See
    following example::

        {
          "logical_disks":
            [
              {
                "size_gb": "MAX",
                "raid_level": "1+0"
              }
            ]
        }

See :ref:`raid` for more details and examples.

Supported properties
~~~~~~~~~~~~~~~~~~~~

The RAID configuration using iRMC driver supports following parameters in
JSON file:

* ``size_gb``: is mandatory properties in Ironic.
* ``raid_level``: is mandatory properties in Ironic. Currently, iRMC Server
  supports following RAID levels: 0, 1, 5, 6, 1+0 and 5+0.
* ``controller``: is name of the controller as read by the RAID interface.
* ``physical_disks``: are specific values for each raid array in
  LogicalDrive which operator want to set them along with ``raid_level``.

The RAID configuration is supported as a manual cleaning step.

.. note::

   * iRMC server will power-on after create/delete raid configuration is
     applied, FGI (Foreground Initialize) will process raid configuration in
     iRMC server, thus the operation will completed upon power-on and power-off
     when created RAID on iRMC server.

See :ref:`raid` for more details and examples.

BIOS configuration Support
^^^^^^^^^^^^^^^^^^^^^^^^^^

The ``irmc`` hardware type provides the iRMC BIOS configuration with ``irmc``
bios interface.

.. warning::
     ``irmc`` bios interface does not support ``factory_reset``.


Configuration
~~~~~~~~~~~~~

The BIOS configuration in the iRMC driver supports the following settings:

- ``boot_option_filter``: Specifies from which drives can be booted. This
  supports following options: ``UefiAndLegacy``, ``LegacyOnly``, ``UefiOnly``.
- ``check_controllers_health_status_enabled``: The UEFI FW checks the
  controller health status. This supports following options: ``true``, ``false``.
- ``cpu_active_processor_cores``: The number of active processor cores 1...n.
  Option 0 indicates that all available processor cores are active.
- ``cpu_adjacent_cache_line_prefetch_enabled``: The processor loads the requested
  cache line and the adjacent cache line. This supports following options:
  ``true``, ``false``.
- ``cpu_vt_enabled``: Supports the virtualization of platform hardware and
  several software environments, based on Virtual Machine Extensions to
  support the use of several software environments using virtual computers.
  This supports following options: ``true``, ``false``.
- ``flash_write_enabled``: The system BIOS can be written. Flash BIOS update
  is possible. This supports following options: ``true``, ``false``.
- ``hyper_threading_enabled``: Hyper-threading technology allows a single
  physical processor core to appear as several logical processors. This
  supports following options: ``true``, ``false``.
- ``keep_void_boot_options_enabled``: Boot Options will not be removed from
  "Boot Option Priority" list. This supports following options: ``true``,
  ``false``.
- ``launch_csm_enabled``: Specifies whether the Compatibility Support Module
  (CSM) is executed. This supports following options: ``true``, ``false``.
- ``os_energy_performance_override_enabled``: Prevents the OS from overruling
  any energy efficiency policy setting of the setup. This supports following
  options: ``true``, ``false``.
- ``pci_aspm_support``: Active State Power Management (ASPM) is used to
  power-manage the PCI Express links, thus consuming less power. This
  supports following options: ``Disabled``, ``Auto``, ``L0Limited``,
  ``L1only``, ``L0Force``.
- ``pci_above_4g_decoding_enabled``: Specifies if memory resources above the
  4GB address boundary can be assigned to PCI devices. This supports
  following options: ``true``, ``false``.
- ``power_on_source``: Specifies whether the switch on sources for the system
  are managed by the BIOS or the ACPI operating system. This supports
  following options: ``BiosControlled``, ``AcpiControlled``.
- ``single_root_io_virtualization_support_enabled``: Single Root IO
  Virtualization Support is active. This supports following
  options: ``true``, ``false``.

The BIOS configuration is supported as a manual cleaning step. See :ref:`bios`
for more details and examples.

Supported platforms
===================
This driver supports FUJITSU PRIMERGY BX S4 or RX S8 servers and above.

- PRIMERGY BX920 S4
- PRIMERGY BX924 S4
- PRIMERGY RX300 S8

When ``irmc`` power interface is used, Soft Reboot (Graceful Reset) and Soft
Power Off (Graceful Power Off) are only available if
`ServerView agents <http://manuals.ts.fujitsu.com/index.php?id=5406-5873-5925-5945-16159>`_
are installed. See `iRMC S4 Manual <http://manuals.ts.fujitsu.com/index.php?id=5406-5873-5925-5988>`_
for more details.

RAID configuration feature supports FUJITSU PRIMERGY servers with
RAID-Ctrl-SAS-6G-1GB(D3116C) controller and above.
For detail supported controller with OOB-RAID configuration, please see
`the whitepaper for iRMC RAID configuration <http://manuals.ts.fujitsu.com/file/12073/wp-svs-oob-raid-hdd-en.pdf>`_.
