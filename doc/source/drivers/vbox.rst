.. _vbox:

==================
VirtualBox drivers
==================

Overview
========

VirtualBox drivers helps to use VirtualBox VMs as bare metals in Ironic.

Ironic has support in ``pxe_ssh`` and ``agent_ssh`` drivers for using a
VirtualBox VM as a bare metal target and do provisioning on it. It works by
connecting via SSH into the VirtualBox host and running commands using
VBoxManage. This works well if you have VirtualBox installed on a Linux box.
But when VirtualBox is installed on a Windows box, configuring and getting SSH
to work with VBoxManage is a difficult (if not impossible) due to following
reasons:

* Windows doesn't come with native SSH support and one needs to use some
  third-party software to enable SSH support on Windows.
* Even after configuring SSH, VBoxManage doesn't work remotely due to how
  Windows manages user accounts - the native Windows user account is different
  from the corresponding SSH user account, and VBoxManage doesn't work
  properly when done with SSH user account.
* Even after tweaking policies of VirtualBox application, the remote
  VBoxManage and VBoxSvc don't sync each other properly and often results in
  a crash.

VirtualBox drivers talk to VirtualBox web service running on the
VirtualBox host using SOAP.  This is primarily intended for Ironic developers
running Windows on their laptops/desktops (although they can be used on other
operating systems as well).  These drivers enables the developers to configure
cloud controller on one VirtualBox VM and use other VMs in the same VirtualBox
as bare metals for the cloud controller.

Currently there three VirtualBox drivers are available :

* ``pxe_vbox`` - Uses iSCSI based deployment mechanism.
* ``agent_vbox`` - Uses agent based deployment mechanism.
* ``fake_vbox`` - Uses VirtualBox for power and management, but uses fake
  deploy.


Setting up development environment
==================================

* Install VirtualBox on your desktop or laptop.

* Create a VM for the cloud controller. Do not power on the VM now.
  For example, ``cloud-controller``.

* In VirtualBox Manager, Select ``cloud-controller`` VM -> Click Settings ->
  Network -> Adapter 2 -> Select 'Enable Network Adapter' ->
  Select Attached to: Internel Network -> Select Name: intnet

* Create a VM in Oracle VirtualBox to act as bare metal. A VM with 1 CPU,
  1 GB memory should be sufficient. Let's name this VM as ``baremetal``.

* In VirtualBox Manager, Select ``baremetal`` VM -> Click Settings ->
  Network -> Adapter 1 -> Select 'Enable Network Adapter' ->
  Select Attached to: Internel Network -> Select Name: intnet

* Configure the VirtualBox web service to disable authentication (This is
  only a suggestion, enable authentication if you want with appropriate
  web service authentication library)::

    VBoxManage setproperty websrvauthlibrary null

* Run VirtualBox web service::

    C:\Program Files\Oracle\VirtualBox\VBoxWebSrv.exe

* Power on the ``cloud-controller`` VM, install GNU/Linux distribution of your
  choice. Setup devstack on it.

* Install ZSI library.

  On ubuntu::

    sudo apt-get install python-ZSI

  On Fedora/RHEL/CentOS::

    sudo yum install python-ZSI

* Install pyremotevbox on ``cloud-controller``::

    sudo pip install pyremotevbox

* Enable ``pxe_vbox`` or ``agent_vbox`` in ``enabled_drivers`` in
  ``/etc/ironic/ironic.conf`` and restart Ironic conductor.

* Setup flat networking on ``eth1`` in ``cloud-controller``. Refer
  :ref:`NeutronFlatNetworking`.

* Enroll the VirtualBox node::

    ironic node-create -d pxe_vbox -i virtualbox_host='10.0.2.2' -i virtualbox_vmname='baremetal'

  If you are using authentication with VirtualBox web service, the Ironic
  node-create looks like the below::

    ironic node-create -d pxe_vbox -i virtualbox_host='10.0.2.2' -i virtualbox_vmname='baremetal' -i virtualbox_username=<username> -i virtualbox_password=<password>

  If VirtualBox web service is listening on another port (than the default
  18083), then the VirtualBox port may be specified using the driver_info
  parameter ``virtualbox_port``.

* Add other Node properties and trigger provisioning on the bare metal node.

  .. note::
    When booting a newly created VM for the first time, VirtualBox
    automatically pops a dialog asking to 'Select start-up disk'. If
    the baremetal VM is powered on for the first time by Ironic during
    provisioning, this dialog will appear. Just press 'Cancel' to
    continue booting the VM.
