.. _irmc:

============
iRMC drivers
============

Overview
========

The iRMC driver enables control FUJITSU PRIMERGY via ServerView
Common Command Interface (SCCI).

There are 3 iRMC drivers:

* ``pxe_irmc``.
* ``iscsi_irmc``
* ``agent_irmc``

Prerequisites
=============

* Install `python-scciclient <https://pypi.python.org/pypi/python-scciclient>`_
  and `pysnmp <https://pypi.python.org/pypi/pysnmp>`_ packages::

  $ pip install "python-scciclient>=0.5.0" pysnmp

Drivers
=======

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
  - ``properties/capabilities`` property to be ``boot_mode:uefi,secure_boot:true`` if
    UEFI Secure Boot is required.

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
  - ``driver_info/irmc_deploy_iso`` property to be either ``deploy iso
    file name``, ``Glance UUID``, ``Glance URL`` or ``Image Service
    URL``.
  - ``instance info/irmc_boot_iso`` property to be either ``boot iso
    file name``, ``Glance UUID``, ``Glance URL`` or ``Image Service
    URL``. This is optional property for ``netboot``.

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
  - ``driver_info/irmc_deploy_iso`` property to be either ``deploy iso
    file name``, ``Glance UUID``, ``Glance URL`` or ``Image Service
    URL``.

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

Functionalities across drivers
==============================

.. _irmc_node_cleaning:

Node Cleaning Support
^^^^^^^^^^^^^^^^^^^^^
The following iRMC drivers support node cleaning:

* ``pxe_irmc``
* ``iscsi_irmc``
* ``agent_irmc``

For more information on node cleaning, see :ref:`cleaning`

Supported **Automated** Cleaning Operations
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

The automated cleaning operations supported are:

* ``restore_irmc_bios_config``:
  Restores BIOS settings on a baremetal node from backup data. If this
  clean step is enabled, the BIOS settings of a baremetal node will be
  backed up automatically before the deployment. By default, this clean
  step is disabled with priority ``0``. Set its priority to a positive
  integer to enable it. The recommended value is ``10``.

Configuration options for the automated cleaning steps are listed under
``[irmc]`` section in ironic.conf ::

  clean_priority_restore_irmc_bios_config = 0

For more information on node automated cleaning, see :ref:`automated_cleaning`

Boot from Remote Volume
^^^^^^^^^^^^^^^^^^^^^^^
The iRMC driver supports the generic iPXE-based remote volume booting when
using the ``pxe_irmc`` classic driver or the following boot interfaces with
the ``irmc`` hardware type:

* ``irmc-pxe``
* ``pxe``

In addition, the iRMC driver also supports remote volume booting without iPXE.
This is available when using the ``irmc-virtual-media`` boot interface with the
``irmc`` hardware type. It is also supported with the following classic
drivers:

* ``iscsi_irmc``
* ``agent_irmc``

This feature configures a node to boot from a remote volume by using the API of
iRMC. It supports iSCSI and FibreChannel.

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
