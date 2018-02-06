.. _irmc:

============
iRMC drivers
============

Overview
========

The iRMC driver enables control FUJITSU PRIMERGY via ServerView
Common Command Interface (SCCI). Support for FUJITSU PRIMERGY servers consists
of the ``irmc`` hardware type and a few hardware interfaces specific for that
hardware type.

Prerequisites
=============

* Install `python-scciclient <https://pypi.python.org/pypi/python-scciclient>`_
  and `pysnmp <https://pypi.python.org/pypi/pysnmp>`_ packages::

  $ pip install "python-scciclient>=0.6.0" pysnmp

Hardware Type
=============

The ``irmc`` hardware type is available for FUJITSU PRIMERGY servers. For
information on how to enable the ``irmc`` hardware type, see
:ref:`enable-hardware-types`.

Hardware interfaces
^^^^^^^^^^^^^^^^^^^

The ``irmc`` hardware type overrides the selection of the following
hardware interfaces:

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
       `Ironic Inspector <https://docs.openstack.org/ironic-inspector/latest/>`_
       needs to be present and configured to use ``inspector`` as the
       inspect interface.

* management
    Supports only ``irmc``.

* power
    Supports only ``irmc``, which enables power control via ServerView Common
    Command Interface (SCCI).

For other hardware interfaces, ``irmc`` hardware type supports the
Bare Metal reference interfaces. For more details about the hardware
interfaces and how to enable the desired ones, see
:ref:`enable-hardware-interfaces`.

Here is a complete configuration example with most of the supported hardware
interfaces enabled for ``irmc`` hardware type.

.. code-block:: ini

   [DEFAULT]
   enabled_hardware_types = irmc
   enabled_boot_interfaces = irmc-virtual-media,irmc-pxe
   enabled_console_interfaces = ipmitool-socat,ipmitool-shellinabox,no-console
   enabled_deploy_interfaces = iscsi,direct
   enabled_inspect_interfaces = irmc,inspector,no-inspect
   enabled_management_interfaces = irmc
   enabled_network_interfaces = flat,neutron
   enabled_power_interfaces = irmc
   enabled_raid_interfaces = no-raid
   enabled_storage_interfaces = noop,cinder
   enabled_vendor_interfaces = no-vendor,ipmitool

Here is a command example to enroll a node with ``irmc`` hardware type.

.. code-block:: console

   openstack baremetal node create --os-baremetal-api-version=1.31 \
      --driver irmc \
      --boot-interface irmc-pxe \
      --deploy-interface direct \
      --inspect-interface irmc

Node configuration
^^^^^^^^^^^^^^^^^^

* Each node is configured for ``irmc`` hardware type by setting the following
  ironic node object’s properties:

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

* The following properties are also required if ``irmc-virtual-media`` boot
  interface is used:

  - ``driver_info/irmc_deploy_iso`` property to be either deploy iso
    file name, Glance UUID, or Image Service URL.
  - ``instance info/irmc_boot_iso`` property to be either boot iso
    file name, Glance UUID, or Image Service URL. This is optional
    property when ``boot_option`` is set to ``netboot``.

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

* Each node can be further configured by setting the following ironic
  node object’s properties which override the parameter values in
  ``[irmc]`` section of ``/etc/ironic/ironic.conf``:

  - ``driver_info/irmc_port`` property overrides ``port``.
  - ``driver_info/irmc_auth_method`` property overrides ``auth_method``.
  - ``driver_info/irmc_client_timeout`` property overrides ``client_timeout``.
  - ``driver_info/irmc_sensor_method`` property overrides ``sensor_method``.
  - ``driver_info/irmc_snmp_version`` property overrides ``snmp_version``.
  - ``driver_info/irmc_snmp_port`` property overrides ``snmp_port``.
  - ``driver_info/irmc_snmp_community`` property overrides ``snmp_community``.
  - ``driver_info/irmc_snmp_security`` property overrides ``snmp_security``.

Upgrading to ``irmc`` hardware type
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

When upgrading from a classic driver to the ``irmc`` hardware type,
make sure you specify the hardware interfaces that are used by the
classic driver. :doc:`/admin/upgrade-to-hardware-types` has more
information, including the hardware interfaces corresponding to
the classic drivers.

Classic Drivers (Deprecated)
============================

These are the classic drivers (deprecated) for FUJITSU PRIMERGY servers.

* ``pxe_irmc``
* ``iscsi_irmc``
* ``agent_irmc``

.. warning::
   The classic drivers are deprecated in the Queens release and will be removed
   in the Rocky release. The ``irmc`` hardware type should be used instead of
   the classic drivers.

pxe_irmc driver
^^^^^^^^^^^^^^^

This driver enables PXE deploy and power control via ServerView Common
Command Interface (SCCI).

Enabling the driver
~~~~~~~~~~~~~~~~~~~

- Add ``pxe_irmc`` to the list of ``enabled_drivers`` in ``[DEFAULT]``
  section of ``/etc/ironic/ironic.conf``.
- Ironic Conductor must be restarted for the new driver to be loaded.

Node configuration
~~~~~~~~~~~~~~~~~~

* Each node is configured for iRMC with PXE deploy by setting the
  following ironic node object’s properties:

  - ``driver`` property to be ``pxe_irmc``
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

* All of nodes are configured by setting the following configuration
  options in ``[irmc]`` section of ``/etc/ironic/ironic.conf``:

  - ``port``: Port to be used for iRMC operations; either 80
    or 443. The default value is 443. Optional.
  - ``auth_method``: Authentication method for iRMC operations;
    either ``basic`` or ``digest``. The default value is ``basic``. Optional.
  - ``client_timeout``: Timeout (in seconds) for iRMC
    operations. The default value is 60. Optional.
  - ``sensor_method``: Sensor data retrieval method; either
    ``ipmitool`` or ``scci``. The default value is ``ipmitool``. Optional.

* The following options are only required for inspection:

  - ``snmp_version``: SNMP protocol version; either ``v1``, ``v2c`` or
    ``v3``. The default value is ``v2c``. Optional.
  - ``snmp_port``: SNMP port. The default value is ``161``. Optional.
  - ``snmp_community``: SNMP community required for versions ``v1``
    and ``v2c``. The default value is ``public``. Optional.
  - ``snmp_security``: SNMP security name required for version ``v3``.
    Optional.

* Each node can be further configured by setting the following ironic
  node object’s properties which override the parameter values in
  ``[irmc]`` section of ``/etc/ironic/ironic.conf``:

  - ``driver_info/irmc_port`` property overrides ``port``.
  - ``driver_info/irmc_auth_method`` property overrides ``auth_method``.
  - ``driver_info/irmc_client_timeout`` property overrides ``client_timeout``.
  - ``driver_info/irmc_sensor_method`` property overrides ``sensor_method``.
  - ``driver_info/irmc_snmp_version`` property overrides ``snmp_version``.
  - ``driver_info/irmc_snmp_port`` property overrides ``snmp_port``.
  - ``driver_info/irmc_snmp_community`` property overrides ``snmp_community``.
  - ``driver_info/irmc_snmp_security`` property overrides ``snmp_security``.


iscsi_irmc driver
^^^^^^^^^^^^^^^^^

This driver enables Virtual Media deploy with image build from
Diskimage Builder and power control via ServerView Common Command
Interface (SCCI).

Enabling the driver
~~~~~~~~~~~~~~~~~~~

- Add ``iscsi_irmc`` to the list of ``enabled_drivers`` in
  ``[DEFAULT]`` section of ``/etc/ironic/ironic.conf``.
- Ironic Conductor must be restarted for the new driver to be loaded.

Node configuration
~~~~~~~~~~~~~~~~~~

* Each node is configured for iRMC with PXE deploy by setting the
  followings ironic node object’s properties:

  - ``driver`` property to be ``iscsi_irmc``
  - ``driver_info/irmc_address`` property to be ``IP address`` or
    ``hostname`` of the iRMC.
  - ``driver_info/irmc_username`` property to be ``username`` for
    the iRMC with administrator privileges.
  - ``driver_info/irmc_password`` property to be ``password`` for
    irmc_username.
  - ``properties/capabilities`` property to be ``boot_mode:uefi`` if
    UEFI boot is required.
  - ``properties/capabilities`` property to be ``secure_boot:true`` if
    Secure Boot is required. Please refer to `UEFI Secure Boot Support`_
    for more information.
  - ``driver_info/irmc_deploy_iso`` property to be either deploy iso
    file name, Glance UUID, or Image Service URL.
  - ``instance info/irmc_boot_iso`` property to be either boot iso
    file name, Glance UUID, or Image Service URL. This is optional
    property when ``boot_option`` is set to ``netboot``.

* All of nodes are configured by setting the following configuration
  options in ``[irmc]`` section of ``/etc/ironic/ironic.conf``:

  - ``port``: Port to be used for iRMC operations; either ``80``
    or ``443``. The default value is ``443``. Optional.
  - ``auth_method``: Authentication method for iRMC operations;
    either ``basic`` or ``digest``. The default value is ``basic``. Optional.
  - ``client_timeout``: Timeout (in seconds) for iRMC
    operations. The default value is 60. Optional.
  - ``sensor_method``: Sensor data retrieval method; either
    ``ipmitool`` or ``scci``. The default value is ``ipmitool``. Optional.
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

* The following options are only required for inspection:

  - ``snmp_version``: SNMP protocol version; either ``v1``, ``v2c`` or
    ``v3``. The default value is ``v2c``. Optional.
  - ``snmp_port``: SNMP port. The default value is ``161``. Optional.
  - ``snmp_community``: SNMP community required for versions ``v1``
    and ``v2c``. The default value is ``public``. Optional.
  - ``snmp_security``: SNMP security name required for version ``v3``.
    Optional.

* Each node can be further configured by setting the following ironic
  node object’s properties which override the parameter values in
  ``[irmc]`` section of ``/etc/ironic/ironic.conf``:

  - ``driver_info/irmc_port`` property overrides ``port``.
  - ``driver_info/irmc_auth_method`` property overrides ``auth_method``.
  - ``driver_info/irmc_client_timeout`` property overrides ``client_timeout``.
  - ``driver_info/irmc_sensor_method`` property overrides ``sensor_method``.
  - ``driver_info/irmc_snmp_version`` property overrides ``snmp_version``.
  - ``driver_info/irmc_snmp_port`` property overrides ``snmp_port``.
  - ``driver_info/irmc_snmp_community`` property overrides ``snmp_community``.
  - ``driver_info/irmc_snmp_security`` property overrides ``snmp_security``.


agent_irmc driver
^^^^^^^^^^^^^^^^^

This driver enables Virtual Media deploy with IPA (Ironic Python
Agent) and power control via ServerView Common Command Interface
(SCCI).

Enabling the driver
~~~~~~~~~~~~~~~~~~~

- Add ``agent_irmc`` to the list of ``enabled_drivers`` in
  ``[DEFAULT]`` section of ``/etc/ironic/ironic.conf``.
- Ironic Conductor must be restarted for the new driver to be loaded.

Node configuration
~~~~~~~~~~~~~~~~~~

* Each node is configured for iRMC with PXE deploy by setting the
  followings ironic node object’s properties:

  - ``driver`` property to be ``agent_irmc``
  - ``driver_info/irmc_address`` property to be ``IP address`` or
    ``hostname`` of the iRMC.
  - ``driver_info/irmc_username`` property to be ``username`` for
    the iRMC with administrator privileges.
  - ``driver_info/irmc_password`` property to be ``password`` for
    irmc_username.
  - ``properties/capabilities`` property to be ``boot_mode:uefi`` if
    UEFI boot is required.
  - ``properties/capabilities`` property to be ``secure_boot:true`` if
    Secure Boot is required. Please refer to `UEFI Secure Boot Support`_
    for more information.
  - ``driver_info/irmc_deploy_iso`` property to be either deploy iso
    file name, Glance UUID, or Image Service URL.
  - ``instance info/irmc_boot_iso`` property to be either boot iso
    file name, Glance UUID, or Image Service URL. This is optional
    property when ``boot_option`` is set to ``netboot``.

* All of nodes are configured by setting the following configuration
  options in ``[irmc]`` section of ``/etc/ironic/ironic.conf``:

  - ``port``: Port to be used for iRMC operations; either 80
    or 443. The default value is 443. Optional.
  - ``auth_method``: Authentication method for iRMC operations;
    either ``basic`` or ``digest``. The default value is ``basic``. Optional.
  - ``client_timeout``: Timeout (in seconds) for iRMC
    operations. The default value is 60. Optional.
  - ``sensor_method``: Sensor data retrieval method; either
    ``ipmitool`` or ``scci``. The default value is ``ipmitool``. Optional.
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

* The following options are only required for inspection:

  - ``snmp_version``: SNMP protocol version; either ``v1``, ``v2c`` or
    ``v3``. The default value is ``v2c``. Optional.
  - ``snmp_port``: SNMP port. The default value is ``161``. Optional.
  - ``snmp_community``: SNMP community required for versions ``v1``
    and ``v2c``. The default value is ``public``. Optional.
  - ``snmp_security``: SNMP security name required for version ``v3``.
    Optional.

* Each node can be further configured by setting the following ironic
  node object’s properties which override the parameter values in
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
The hardware type ``irmc`` (and all iRMC classic drivers) supports secure boot
deploy.

.. warning::
     Secure boot feature is not supported with ``pxe`` boot interface.

The UEFI secure boot can be configured by adding ``secure_boot`` parameter,
which is a boolean value. Enabling the secure boot is different when
Bare Metal service is used with Compute service or without Compute service. The
following sections describes both methods:

* Enabling secure boot with Compute service:
  To enable secure boot we need to set a capability on the bare metal node
  and the bare metal flavor, for example::

    openstack baremetal node set <node-uuid> --property capabilities='secure_boot:true'
    openstack flavor set FLAVOR-NAME --property capabilities:secure_boot="true"

* Enabling secure boot without Compute service:
  Since adding capabilities to the node's properties is only used by the nova
  scheduler to perform more advanced scheduling of instances, we need
  to enable secure boot without nova, for example::

    openstack baremetal node set <node-uuid> --instance-info capabilities='{"secure_boot": "true"}'

.. _irmc_node_cleaning:

Node Cleaning Support
^^^^^^^^^^^^^^^^^^^^^
The ``irmc`` hardware type (and all iRMC classic drivers) supports node
cleaning. For more information on node cleaning, see :ref:`cleaning`.

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
The ``irmc`` hardware type (and ``pxe_irmc`` classic driver) supports the
generic iPXE-based remote volume booting when using the following boot
interfaces:

* ``irmc-pxe``
* ``pxe``

In addition, the ``irmc`` hardware type supports remote volume booting without
iPXE. This is available when using the ``irmc-virtual-media`` boot interface
(and ``iscsi_irmc`` and ``agent_irmc`` classic drivers). This feature
configures a node to boot from a remote volume by using the API of iRMC. It
supports iSCSI and FibreChannel.

Configuration
~~~~~~~~~~~~~

In addition to the configuration for generic drivers to
:ref:`remote volume boot <boot-from-volume>`,
the iRMC drivers require the following configuration:

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

      openstack baremetal node set $NODE_UUID \
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

    openstack baremetal node set $NODE_UUID --driver-info irmc_storage_network_size=22

Supported hardware
~~~~~~~~~~~~~~~~~~

The drivers support the PCI controllers, Fibrechannel Cards, Converged Network
Adapters supported by
`Fujitsu ServerView Virtual-IO Manager <http://www.fujitsu.com/fts/products/computing/servers/primergy/management/primergy-blade-server-io-virtualization.html>`_.

Hardware Inspection Support
^^^^^^^^^^^^^^^^^^^^^^^^^^^

The ``irmc`` hardware type (and all iRMC classic drivers) provides the
iRMC-specific hardware inspection with ``irmc`` inspect interface.

.. note::
   SNMP requires being enabled in ServerView® iRMC S4 Web Server(Network
   Settings\SNMP section).

Configuration
~~~~~~~~~~~~~

The Hardware Inspection Support in the iRMC drivers requires the following
configuration:

* It is necessary to set ironic configuration with ``gpu_ids`` option
  in ``[irmc]`` section.

  ``gpu_ids`` is a list of ``<vendorID>/<deviceID>`` where:

  - ``<vendorID>``: 4 hexadecimal digits starts with '0x'.
  - ``<deviceID>``: 4 hexadecimal digits starts with '0x'.

  Here is a sample value for gpu_ids::

    gpu_ids = 0x1000/0x0079,0x2100/0x0080

* The python-scciclient package requires pyghmi version >= 1.0.22 and pysnmp
  version >= 4.2.3. They are used by the conductor service on the conductor.
  The latest version of pyghmi can be downloaded from `here
  <https://pypi.python.org/pypi/pyghmi/>`__
  and pysnmp can be downloaded from `here
  <https://pypi.python.org/pypi/pysnmp/>`__.

Supported properties
~~~~~~~~~~~~~~~~~~~~

The inspection process will discover the following essential properties
(properties required for scheduling deployment):

* ``memory_mb``: memory size

* ``cpus``: number of cpus

* ``cpu_arch``: cpu architecture

* ``local_gb``: disk size

Inspection can also discover the following extra capabilities for iRMC
drivers:

* ``irmc_firmware_version``: iRMC firmware version

* ``rom_firmware_version``: ROM firmware version

* ``trusted_boot``: The flag whether TPM(Trusted Platform Module) is
  supported by the server. The possible values are 'True' or 'False'.

* ``server_model``: server model

* ``pci_gpu_devices``: number of gpu devices connected to the bare metal.

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

Supported platforms
===================
This driver supports FUJITSU PRIMERGY BX S4 or RX S8 servers and above.

- PRIMERGY BX920 S4
- PRIMERGY BX924 S4
- PRIMERGY RX300 S8

Soft Reboot (Graceful Reset) and Soft Power Off (Graceful Power Off)
are only available if `ServerView agents <http://manuals.ts.fujitsu.com/index.php?id=5406-5873-5925-5945-16159>`_
are installed. See `iRMC S4 Manual <http://manuals.ts.fujitsu.com/index.php?id=5406-5873-5925-5988>`_
for more details.
