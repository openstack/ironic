===========
IPMI driver
===========

Overview
========

The ``ipmi``  hardware type manage nodes by using IPMI_ (Intelligent Platform
Management Interface) protocol versions 2.0 or 1.5. It uses the IPMItool_
utility which is an open-source command-line interface (CLI) for controlling
IPMI-enabled devices.

Glossary
========

* IPMI_ - Intelligent Platform Management Interface.
* IPMB - Intelligent Platform Management Bus/Bridge.
* BMC_  - Baseboard Management Controller.
* RMCP - Remote Management Control Protocol.

Enabling the IPMI hardware type
===============================

Please see :doc:`/install/configure-ipmi` for the required dependencies.

#. The ``ipmi`` hardware type is enabled by default starting with the Ocata
   release. To enable it explicitly, add the following to your ``ironic.conf``:

   .. code-block:: ini

    [DEFAULT]
    enabled_hardware_types = ipmi
    enabled_management_interfaces = ipmitool,noop
    enabled_power_interfaces = ipmitool

   Optionally, enable the :doc:`vendor passthru interface
   </contributor/vendor-passthru>` and either or both :doc:`console interfaces
   </admin/console>`:

   .. code-block:: ini

    [DEFAULT]
    enabled_hardware_types = ipmi
    enabled_console_interfaces = ipmitool-socat,ipmitool-shellinabox,no-console
    enabled_management_interfaces = ipmitool,noop
    enabled_power_interfaces = ipmitool
    enabled_vendor_interfaces = ipmitool,no-vendor

#. Restart the Ironic conductor service.

Please see :doc:`/install/enabling-drivers` for more details.

Registering a node with the IPMI driver
=======================================

Nodes configured to use the IPMItool drivers should have the ``driver`` field
set to ``ipmi``.

The following configuration value is required and has to be added to
the node's ``driver_info`` field:

- ``ipmi_address``: The IP address or hostname of the BMC.

Other options may be needed to match the configuration of the BMC, the
following options are optional, but in most cases, it's considered a
good practice to have them set:

- ``ipmi_username``: The username to access the BMC; defaults to *NULL* user.
- ``ipmi_password``: The password to access the BMC; defaults to *NULL*.
- ``ipmi_port``: The remote IPMI RMCP port. By default ipmitool will
  use the port *623*.

.. note::
   It is highly recommend that you setup a username and password for
   your BMC.

The ``baremetal node create`` command can be used to enroll a node
with an IPMItool-based driver. For example::

    baremetal node create --driver ipmi \
        --driver-info ipmi_address=<address> \
        --driver-info ipmi_username=<username> \
        --driver-info ipmi_password=<password>

Advanced configuration
======================

When a simple configuration such as providing the ``address``,
``username`` and ``password`` is not enough, the IPMItool driver contains
many other options that can be used to address special usages.

Single/Double bridging functionality
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. note::
   A version of IPMItool higher or equal to 1.8.12 is required to use
   the bridging functionality.

There are two different bridging functionalities supported by the
IPMItool-based drivers: *single* bridge and *dual* bridge.

The following configuration values need to be added to the node's
``driver_info`` field so bridging can be used:

- ``ipmi_bridging``: The bridging type; default is *no*; other supported
  values are *single* for single bridge or *dual* for double bridge.
- ``ipmi_local_address``: The local IPMB address for bridged requests.
   Required only if ``ipmi_bridging`` is set to *single* or *dual*. This
   configuration is optional, if not specified it will be auto discovered
   by IPMItool.
- ``ipmi_target_address``: The destination address for bridged
  requests. Required only if ``ipmi_bridging`` is set to *single* or *dual*.
- ``ipmi_target_channel``: The destination channel for bridged
  requests. Required only if ``ipmi_bridging`` is set to *single* or *dual*.

Double bridge specific options:

- ``ipmi_transit_address``: The transit address for bridged
  requests. Required only if ``ipmi_bridging`` is set to *dual*.
- ``ipmi_transit_channel``: The transit channel for bridged
  requests. Required only if ``ipmi_bridging`` is set to *dual*.


The parameter ``ipmi_bridging`` should specify the type of bridging
required: *single* or *dual* to access the bare metal node. If the
parameter is not specified, the default value will be set to *no*.

The ``baremetal node set`` command can be used to set the required
bridging information to the Ironic node enrolled with the IPMItool
driver. For example:

* Single Bridging::

    baremetal node set <UUID or name> \
        --driver-info ipmi_local_address=<address> \
        --driver-info ipmi_bridging=single \
        --driver-info ipmi_target_channel=<channel> \
        --driver-info ipmi_target_address=<target address>

* Double Bridging::

    baremetal node set <UUID or name> \
        --driver-info ipmi_local_address=<address> \
        --driver-info ipmi_bridging=dual \
        --driver-info ipmi_transit_channel=<transit channel> \
        --driver-info ipmi_transit_address=<transit address> \
        --driver-info ipmi_target_channel=<target channel> \
        --driver-info ipmi_target_address=<target address>

Changing the version of the IPMI protocol
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

The IPMItool-based drivers works with the versions *2.0* and *1.5* of the
IPMI protocol. By default, the version *2.0* is used.

In order to change the IPMI protocol version in the bare metal node,
the following option needs to be set to the node's ``driver_info`` field:

- ``ipmi_protocol_version``: The version of the IPMI protocol; default
  is *2.0*. Supported values are *1.5* or *2.0*.

The ``baremetal node set`` command can be used to set the desired
protocol version::

    baremetal node set <UUID or name> --driver-info ipmi_protocol_version=<version>

.. warning::
   Version *1.5* of the IPMI protocol does not support encryption.
   Therefore, it is highly recommended that version 2.0 is used.

.. _ipmi-cipher-suites:

Cipher suites
~~~~~~~~~~~~~

IPMI 2.0 introduces support for encryption and allows setting which cipher
suite to use. Traditionally, ``ipmitool`` was using cipher suite 3 by default,
but since SHA1 no longer complies with modern security requirement, recent
versions (e.g. the one used in RHEL 8.2) are switching to suite 17.

Normally, the cipher suite to use is negotiated with the BMC using the special
command. On some hardware the negotiation yields incorrect results and IPMI
commands fail with
::

    Error in open session response message : no matching cipher suite
    Error: Unable to establish IPMI v2 / RMCP+ session

Another possible problem is ``ipmitool`` commands taking very long (tens of
seconds or even minutes) because the BMC does not support cipher suite
negotiation. In both cases you can specify the required suite yourself, e.g.

.. code-block:: console

    baremetal node set <UUID or name> --driver-info ipmi_cipher_suite=3

In scenarios where the operator can't specify the ``ipmi_cipher_suite`` for
each node, the configuration parameter ``[ipmi]/cipher_suite_versions`` can be
set to a list of cipher suites that will be used, Ironic will attempt to find
a value that can be used from the list provided (from last to first):

.. code-block:: ini

  [ipmi]
  cipher_suite_versions = ['1','2','3','6','7','8','11','12']

To find the suitable values for this configuration, you can check the field
`RMCP+ Cipher Suites` after running an ``ipmitool`` command, e.g:

.. code-block:: console

  $ ipmitool -I lanplus -H $HOST -U $USER -v -R 12 -N 5  lan print
  # output
  Set in Progress         : Set Complete
  Auth Type Support       : NONE MD2 MD5 PASSWORD OEM
  Auth Type Enable        : Callback : NONE MD2 MD5 PASSWORD OEM
  IP Address Source       : Static Address
  IP Address              : <IP>
  Subnet Mask             : <Subnet>
  MAC Address             : <MAC>
  RMCP+ Cipher Suites     : 0,1,2,3,6,7,8,11,12

.. warning::
   Only the cipher suites 3 and 17 are considered secure by the modern
   standards. Cipher suite 0 means "no security at all".

.. _ipmi-priv-level:

Using a different privilege level
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

By default Ironic requests the ``ADMINISTRATOR`` privilege level of all
commands. This is the easiest option, but if it's not available for you, you
can change it to ``CALLBACK``, ``OPERATOR`` or ``USER`` this way:

.. code-block:: console

    baremetal node set <UUID or name> --driver-info ipmi_priv_level=OPERATOR

You must ensure that the user can still change power state and boot devices.

Static boot order configuration
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

See :ref:`static-boot-order`.

.. TODO(lucasagomes): Write about privilege level
.. TODO(lucasagomes): Write about force boot device

Vendor Differences
~~~~~~~~~~~~~~~~~~

While the Intelligent Platform Management Interface (IPMI) interface is based
upon a defined standard, the Ironic community is aware of at least one vendor
which utilizes a non-standard boot device selector. In essence, this could be
something as simple as different interpretation of the standard.

As of October 2020, the known difference is with Supermicro hardware where
a selector of ``0x24``, signifying a *REMOTE* boot device in the standard,
must be used when a boot operation from the local disk subsystem is requested
**in UEFI mode**. This is contrary to BIOS mode where the same BMC's expect
the selector to be a value of ``0x08``.

Because the BMC does not respond with any sort of error, nor do we want to
risk BMC connectivity issues by explicitly querying all BMCs what vendor it may
be before every operation, the vendor can automatically be recorded in the
``properties`` field ``vendor``. When this is set to a value of
``supermicro``, Ironic will navigate the UEFI behavior difference enabling
the UEFI to be requested with boot to disk.

Example::

    baremetal node set <UUID or name> \
        --properties vendor="supermicro"

Luckily, Ironic will attempt to perform this detection in power
synchronization process, and record this value if not already set.

While similar issues may exist when setting the boot mode and target
boot device in other vendors' BMCs, we are not aware of them at present.
Should you encounter such an issue, please feel free to report this via
`Storyboard <https://storyboard.openstack.org>`_, and be sure to include
the ``chassis bootparam get 5`` output value along with the ``mc info``
output from your BMC.

Example::

    ipmitool -I lanplus -H <BMC ADDRESS> -U <Username> -P <Password> \
        mc info
    ipmitool -I lanplus -H <BMC ADDRESS> -U <Username> -P <Password> \
        chassis bootparam get 5

.. _IPMItool: https://sourceforge.net/projects/ipmitool/
.. _IPMI: https://en.wikipedia.org/wiki/Intelligent_Platform_Management_Interface
.. _BMC: https://en.wikipedia.org/wiki/Intelligent_Platform_Management_Interface#Baseboard_management_controller
