.. _WOL:

==================
Wake-On-Lan driver
==================

Overview
========

Wake-On-Lan is a standard that allows a computer to be powered on by a
network message. This is widely available and doesn't require any fancy
hardware to work with [1]_.

The Wake-On-Lan driver is a **testing** driver not meant for
production. And useful for users that wants to try Ironic with real
bare metal instead of virtual machines.

It's important to note that Wake-On-Lan is only capable of powering on
the machine. When power off is called the driver won't take any action
and will just log a message, the power off require manual intervention
to be performed.

Also, since Wake-On-Lan does not offer any means to determine the current
power state of the machine, the driver relies on the power state set in
the Ironic database. Any calls to the API to get the power state of the
node will return the value from the Ironic's database.


Drivers
=======

pxe_wol
^^^^^^^

Overview
~~~~~~~~

The ``pxe_wol`` driver uses the Wake-On-Lan technology to control the
power state, PXE/iPXE technology for booting and the iSCSI methodology
for deploying the node.

Requirements
~~~~~~~~~~~~

* Wake-On-Lan should be enabled in the BIOS

Configuring and Enabling the driver
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

1. Add ``pxe_wol`` to the list of ``enabled_drivers`` in
   */etc/ironic/ironic.conf*. For example::

    [DEFAULT]
    ...
    enabled_drivers = pxe_ipmitool,pxe_wol

2. Restart the Ironic conductor service::

    service ironic-conductor restart

Registering a node with the Wake-On-Lan driver
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Nodes configured for Wake-On-Lan driver should have the ``driver``
property set to ``pxe_wol``.

The node should have at least one port registered with it because the
Wake-On-Lan driver will use the MAC address of the ports to create the
magic packet [2]_.

The following configuration values are optional and can be added to the
node's ``driver_info`` as needed to match the network configuration:

- ``wol_host``: The broadcast IP address; defaults to
  **255.255.255.255**.
- ``wol_port``: The destination port; defaults to **9**.

.. note::
  Say the ``ironic-conductor`` is connected to more than one network and
  the node you are trying to wake up is in the ``192.0.2.0/24`` range. The
  ``wol_host`` configuration should be set to **192.0.2.255** (the
  broadcast IP) so the packets will get routed correctly.

The following sequence of commands can be used to enroll a node with
the Wake-On-Lan driver.

1. Create node::

    ironic node-create -d pxe_wol [-i wol_host=<broadcast ip> [ -i
    wol_port=<destination port>]]

The above command ``ironic node-create`` will return UUID of the node,
which is the value of *$NODE* in the following command.

2. Associate port with the node created::

    ironic port-create -n $NODE -a <MAC address>


agent_wol
^^^^^^^^^

Overview
~~~~~~~~

The ``agent_wol`` driver uses the Wake-On-Lan technology to control the
power state, PXE/iPXE technology for booting and the Ironic Python Agent
for deploying the node.

Additional requirements
~~~~~~~~~~~~~~~~~~~~~~~

* Boot device order should be set to "PXE, DISK" in the BIOS setup

* BIOS must try next boot device if PXE boot failed

* Automated cleaning should be disabled, see :ref:`automated_cleaning`

* Node should be powered off before start of deploy

Configuration steps are the same as for ``pxe_wol`` driver, replace "pxe_wol"
with "agent_wol".


References
==========
.. [1] Wake-On-Lan - https://en.wikipedia.org/wiki/Wake-on-LAN
.. [2] Magic packet - https://en.wikipedia.org/wiki/Wake-on-LAN#Sending_the_magic_packet
