.. _IPMITOOL:

===============
IPMITool driver
===============

Overview
========

The IPMITool driver enables managing nodes by using the Intelligent
Platform Management Interface (IPMI) versions 2.0 or 1.5. The name of
the driver comes from the utility ``ipmitool`` which is an open-source
command-line interface (CLI) for controlling IPMI-enabled devices.

Currently there are 2 IPMITool drivers:

* ``agent_ipmitool``
* ``pxe_ipmitool``

Glossary
========

* IPMI - Intelligent Platform Management Interface.
* IPMB - Intelligent Platform Management Bus/Bridge.
* BMC  - Baseboard Management Controller.
* RMCP - Remote Management Control Protocol.

Prerequisites
=============

* The `ipmitool utility <https://sourceforge.net/projects/ipmitool>`_
  should be installed on the ironic conductor node. On most distros,
  this is provided as part of the ``ipmitool`` package.

Enabling the IPMITool driver(s)
===============================

.. note::
    The ``pxe_ipmitool`` driver is the default driver in Ironic, so if
    no extra configuration is provided the driver will be enabled.

#. Add ``pxe_ipmitool`` and/or ``agent_ipmitool`` to the list of
   ``enabled_drivers`` in */etc/ironic/ironic.conf*. For example::

    [DEFAULT]
    ...
    enabled_drivers = pxe_ipmitool,agent_ipmitool

#. Restart the Ironic conductor service::

    service ironic-conductor restart

Registering a node with the IPMItool driver
===========================================

Nodes configured to use the IPMItool drivers should have the ``driver``
property set to ``pxe_ipmitool`` or ``agent_ipmitool``.

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

The ``ironic node-create`` command can be used to enroll a node with
the IPMITool driver. For example::

    ironic node-create -d pxe_ipmitool -i ipmi_address=<address>
    -i ipmi_username=<username> -i ipmi_password=<password>

Advanced configuration
======================

When a simple configuration such as providing the ``address``,
``username`` and ``password`` is not enough, the IPMItool driver contains
many other options that can be used to address special usages.

Single/Double bridging functionality
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. note::
   A version of ``ipmitool`` higher or equal to 1.8.12 is required to use
   the bridging functionality.

There are two different bridging functionalities supported by the
IPMITool driver: *single* bridge and *dual* bridge.

The following configuration values need to be added to the node's
``driver_info`` field so bridging can be used:

- ``ipmi_bridging``: The bridging type; default is *no*; other supported
  values are *single* for single bridge or *dual* for double bridge.
- ``ipmi_local_address``: The local IPMB address for bridged requests.
   Required only if ``ipmi_bridging`` is set to *single* or *dual*. This
   configuration is optional, if not specified it will be auto discovered
   by ipmitool.
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

The ``ironic node-update`` command can be used to set the required
bridging information to the Ironic node enrolled with the IPMItool
driver. For example:

* Single Bridging::

    ironic node-update add <UUID or name> driver_info/ipmi_local_address=<address>
    driver_info/ipmi_bridging=single driver_info/ipmi_target_channel=<channel>
    driver_info/ipmi_target_address=<target address>

* Double Bridging::

    ironic node-update add <UUID or name> driver_info/ipmi_local_address=<address>
    driver_info/ipmi_bridging=dual driver_info/ipmi_transit_channel=<transit channel>
    driver_info/ipmi_transit_address=<transit address> driver_info/ipmi_target_channel=<target channel>
    driver_info/ipmi_target_address=<target address>

Changing the version of the IPMI protocol
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

The IPMItool driver works with the versions *2.0* and *1.5* of the
IPMI protocol. By default, the version *2.0* is used.

In order to change the IPMI protocol version in the bare metal node,
the following option needs to be set to the node's ``driver_info`` field:

- ``ipmi_protocol_version``: The version of the IPMI protocol; default
  is *2.0*. Supported values are *1.5* or *2.0*.

The ``ironic node-update`` command can be used to set the desired
protocol version::

    ironic node-update add <UUID or name> driver_info/ipmi_protocol_version=<version>

.. warning::
   The version *1.5* of the IPMI protocol does not support encryption. So
   it's very recommended that the version *2.0* is used.

.. TODO(lucasagomes): Write about privilege level
.. TODO(lucasagomes): Write about force boot device
