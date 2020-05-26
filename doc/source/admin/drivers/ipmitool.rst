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

The ``openstack baremetal node create`` command can be used to enroll a node
with an IPMItool-based driver. For example::

    openstack baremetal node create --driver ipmi \
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

The ``openstack baremetal node set`` command can be used to set the required
bridging information to the Ironic node enrolled with the IPMItool
driver. For example:

* Single Bridging::

    openstack baremetal node set <UUID or name> \
        --driver-info ipmi_local_address=<address> \
        --driver-info ipmi_bridging=single \
        --driver-info ipmi_target_channel=<channel> \
        --driver-info ipmi_target_address=<target address>

* Double Bridging::

    openstack baremetal node set <UUID or name> \
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

The ``openstack baremetal node set`` command can be used to set the desired
protocol version::

    openstack baremetal node set <UUID or name> --driver-info ipmi_protocol_version=<version>

.. warning::
   Version *1.5* of the IPMI protocol does not support encryption.
   Therefore, it is highly recommended that version 2.0 is used.

Static boot order configuration
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

See :ref:`static-boot-order`.

.. TODO(lucasagomes): Write about privilege level
.. TODO(lucasagomes): Write about force boot device

.. _IPMItool: https://sourceforge.net/projects/ipmitool/
.. _IPMI: https://en.wikipedia.org/wiki/Intelligent_Platform_Management_Interface
.. _BMC: https://en.wikipedia.org/wiki/Intelligent_Platform_Management_Interface#Baseboard_management_controller
