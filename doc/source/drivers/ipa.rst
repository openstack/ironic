.. _IPA:

===================
Ironic Python Agent
===================

Overview
========

*Ironic Python Agent* (also often called *IPA* or just *agent*) is a
Python-based agent which handles *ironic* bare metal nodes in a
variety of actions such as inspect, configure, clean and deploy images.
IPA is distributed over nodes and runs, inside of a ramdisk, the
process of booting this ramdisk on the node.

For more information see the `ironic-python-agent documentation
<http://docs.openstack.org/developer/ironic-python-agent/>`_.

Drivers
=======

Starting with the Kilo release all drivers (except for fake ones) are using
IPA for deployment. There are two types of them, which can be distinguished
by prefix:

* For drivers with ``pxe_`` or ``iscsi_`` prefix IPA exposes the root hard
  drive as an iSCSI share and calls back to the ironic conductor. The
  conductor mounts the share and copies an image there. It then signals back
  to IPA for post-installation actions like setting up a bootloader for local
  boot support.

* For drivers with ``agent_`` prefix the conductor prepares a swift temporary
  URL for an image. IPA then handles the whole deployment process:
  downloading an image from swift, putting it on the machine and doing any
  post-deploy actions.

Which one to choose depends on your environment. iSCSI-based drivers put
higher load on conductors, agent-based drivers currently require the whole
image to fit in the node's memory.

.. todo: other differences?

.. todo: explain configuring swift for temporary URL's

Requirements
~~~~~~~~~~~~

Using IPA requires it to be present and configured on the deploy ramdisk, see
:ref:`BuildingDeployRamdisk` for details.
