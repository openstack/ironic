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

* Install `python-scciclient package <https://pypi.python.org/pypi/python-scciclient>`_::

  $ pip install "python-scciclient>=0.4.0"

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


Supported platforms
===================
This driver supports FUJITSU PRIMERGY BX S4 or RX S8 servers and above.

- PRIMERGY BX920 S4
- PRIMERGY BX924 S4
- PRIMERGY RX300 S8
