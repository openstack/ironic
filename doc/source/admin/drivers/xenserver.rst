.. _xenserver:
.. _bug 1498576: https://bugs.launchpad.net/diskimage-builder/+bug/1498576

=================
XenServer drivers
=================

Overview
========

XenServer drivers can be used to deploy hosts with Ironic by using XenServer
VMs to simulate bare metal nodes.

Ironic provides support via the ``pxe_ssh`` and ``agent_ssh`` drivers for
using a XenServer VM as a bare metal target and do provisioning on it. It
works by connecting via SSH into the XenServer host and running commands using
the 'xe' command.

This is particularly useful for deploying overclouds that use XenServer for VM
hosting as the Compute node must be run as a virtual machine on the XenServer
host it will be controlling.  In this case, one VM per hypervisor needs to be
installed.

This support has been tested with XenServer 6.5.

Usage
=====

* Install the VMs using the "Other Install Media" template, which will ensure
  that they are HVM guests

* Set the HVM guests to boot from network first

* If your generated initramfs does not have the fix for `bug 1498576`_,
  disable the Xen PV drivers as a work around

::

 xe vm-param-set uuid=<uuid> xenstore-data:vm-data="vm_data/disable_pf: 1"


