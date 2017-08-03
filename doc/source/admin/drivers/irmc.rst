.. _irmc:

============
iRMC drivers
============

Overview
========

The iRMC driver enables control FUJITSU PRIMERGY via ServerView
Common Command Interface (SCCI).

Support for FUJITSU PRIMERGY servers consists of the ``irmc`` hardware
type, along with three classic drivers that were instituted before the
implementation of the functionality enabling the hardware type.

The classic drivers are:

* ``pxe_irmc``
* ``iscsi_irmc``
* ``agent_irmc``

Prerequisites
=============

* Install `python-scciclient <https://pypi.python.org/pypi/python-scciclient>`_
  and `pysnmp <https://pypi.python.org/pypi/pysnmp>`_ packages::

  $ pip install "python-scciclient>=0.5.0" pysnmp

Hardware Type
=============

The ``irmc`` hardware type is introduced to support the new Ironic driver
model. It is recommended to use ``irmc`` hardware type for FUJITSU PRIMERGY
hardware instead of the classic drivers.

For how to enable ``irmc`` hardware type, see :ref:`enable-hardware-types`.

Hardware interfaces
^^^^^^^^^^^^^^^^^^^

The ``irmc`` hardware type overrides the selection of the following
hardware interfaces:

* boot
    Supports ``irmc-virtual-media``, ``irmc-pxe``, and ``pxe``.
    The default is ``irmc-virtual-media``.

    .. warning::
       We deprecated the ``pxe`` boot interface when used with ``irmc``
       hardware type. Support for this interface will be removed in the
       future. Instead, use ``irmc-pxe``. ``irmc-pxe`` boot interface
       was introduced in Pike and is used in the ``pxe_irmc`` classic
       driver.

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
    Supports only ``irmc``.

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

Upgrading to ``irmc`` hardware type
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

When upgrading from a classic driver to the ``irmc`` hardware type,
make sure you specify the hardware interfaces that are used by the
classic driver. :doc:`/admin/upgrade-to-hardware-types` has more
information, including the hardware interfaces corresponding to
the classic drivers.

Classic Drivers
===============

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
The ``irmc`` hardware type and the following iRMC classic drivers support
node cleaning:

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
The iRMC driver supports the generic iPXE based remote volume booting when
you use ``pxe_irmc`` classic driver or the following boot interfaces with
the ``irmc`` hardware type.

* ``irmc-pxe``
* ``pxe``

The iRMC driver also supports a remote volume booting without iPXE. How to use this iRMC
specific remote volume booting is described here.

The ``irmc-virtual-media`` boot interface supports this feature for the
``irmc`` hardware type. This feature is also supported with following classic
drivers:

* ``iscsi_irmc``
* ``agent_irmc``

This feature configures a node to boot from a remote volume by using API of
iRMC. It supports iSCSI and FibreChannel.

Configuration
~~~~~~~~~~~~~

In addition to configuration for generic drivers for the remote volume boot,
the drivers require the following configuration.

* It is necessary to set physical port IDs to network ports and volume
  connectors. All cards including those not used for volume boot should be
  registered.

  - A physical ID format is: ``<Card Type><Slot No>-<Port No>`` where:

    - ``<Card Type>``: could be a ``LAN``, ``FC`` or ``CNA``
    - ``<Slot No>``: 0 indicates onboard slot. Use 1 to 9 for add-on slots.
    - ``<Port No>``: A port number. It starts from 1.

  - Set the IDs to ``driver_info/irmc_pci_physical_ids`` of a Node. This
    parameter is a dictionary of pair of UUID of a resource (Port or Volume
    connector) and a physical ID. This parameter can be set with the following
    command::

      openstack baremetal node set $NODE_UUID --driver-info irmc_pci_physical_ids={} \
      --driver-info irmc_pci_physical_ids/$PORT_UUID=LAN0-1 \
      --driver-info irmc_pci_physical_ids/$VOLUME_CONNECTOR_UUID=CNA1-1

* For iSCSI boot, volume connectors with both type ``iqn`` and ``ip`` are
  required. The configuration with DHCP is not supported yet.

* For iSCSI, the size of the storage network is needed. This value should be
  set to ``driver_info/irmc_storage_network_size`` of a Node as an integer.
  For example, if your storage network is 10.2.0.0/22, use the following
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
