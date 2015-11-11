.. _IBOOT:

============
iBoot driver
============

Overview
========
The iBoot power driver enables you to take advantage of power cycle
management of nodes using Dataprobe iBoot devices over the DxP protocol.

Drivers
=======

There are two iboot drivers:

* The ``pxe_iboot`` driver uses iBoot to control the power state of the
  node, PXE/iPXE technology for booting and the iSCSI methodology for
  deploying the node.

* The ``agent_iboot`` driver uses iBoot to control the power state of the
  node, PXE/iPXE technology for booting and the Ironic Python Agent for
  deploying an image to the node.

Requirements
~~~~~~~~~~~~

* ``python-iboot`` library should be installed - https://github.com/darkip/python-iboot

Tested platforms
~~~~~~~~~~~~~~~~

* iBoot-G2

Configuring and enabling the driver
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

1. Add ``pxe_iboot`` and/or ``agent_iboot`` to the list of ``enabled_drivers``
   in */etc/ironic/ironic.conf*. For example::

    [DEFAULT]
    ...
    enabled_drivers = pxe_iboot,agent_iboot

2. Restart the Ironic conductor service::

    service ironic-conductor restart

Registering a node with the iBoot driver
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Nodes configured for the iBoot driver should have the ``driver`` property
set to ``pxe_iboot`` or ``agent_iboot``.

The following configuration values are also required in ``driver_info``:

- ``iboot_address``: The IP address of the iBoot PDU.
- ``iboot_username``: User name used for authentication.
- ``iboot_password``: Password used for authentication.

In addition, there are optional properties in ``driver_info``:

- ``iboot_port``: iBoot PDU port. Defaults to 9100.
- ``iboot_relay_id``: iBoot PDU relay ID. This option is useful in order
  to support multiple nodes attached to a single PDU. Defaults to 1.

The following sequence of commands can be used to enroll a node with
the iBoot driver.

1. Create node::

    ironic node-create -d pxe_iboot -i iboot_username=<username> -i iboot_password=<password> -i iboot_address=<address>

References
==========
.. [1] iBoot-G2 official documentation - http://dataprobe.com/support_iboot-g2.html
