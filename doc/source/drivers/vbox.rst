.. _vbox:

==================
VirtualBox drivers
==================

Overview
========

VirtualBox drivers can be used to test Ironic by using VirtualBox VMs to
simulate bare metal nodes.

Ironic provides support via the ``pxe_ssh`` and ``agent_ssh`` drivers for using
a VirtualBox VM as a bare metal target and do provisioning on it. It works by
connecting via SSH into the VirtualBox host and running commands using
VBoxManage. This works well if you have VirtualBox installed on a Linux box.
But when VirtualBox is installed on a Windows box, configuring and getting SSH
to work with VBoxManage is difficult (if not impossible) due to the following
reasons:

* Windows doesn't come with native SSH support and one needs to use some
  third-party software to enable SSH support on Windows.
* Even after configuring SSH, VBoxManage doesn't work remotely due to how
  Windows manages user accounts -- the native Windows user account is different
  from the corresponding SSH user account, and VBoxManage doesn't work
  properly when done with the SSH user account.
* Even after tweaking the policies of the VirtualBox application, the remote
  VBoxManage and VBoxSvc don't sync each other properly and often results in
  a crash.

VirtualBox drivers use SOAP to talk to the VirtualBox web service running on
the VirtualBox host. These drivers are primarily intended for Ironic developers
running Windows on their laptops/desktops, although they can be used on other
operating systems as well.  Using these drivers, a developer could configure a
cloud controller on one VirtualBox VM and use other VMs in the same VirtualBox
as bare metals for that cloud controller.

These VirtualBox drivers are available :

* ``pxe_vbox``: uses iSCSI-based deployment mechanism.
* ``agent_vbox``: uses agent-based deployment mechanism.
* ``fake_vbox``: uses VirtualBox for power and management, but uses fake
  deploy.


Setting up development environment
==================================

* Install VirtualBox on your desktop or laptop.

* Create a VM for the cloud controller. Do not power on the VM now.
  For example, ``cloud-controller``.

* In VirtualBox Manager, Select ``cloud-controller`` VM -> Click Settings ->
  Network -> Adapter 2 -> Select 'Enable Network Adapter' ->
  Select Attached to: Internal Network -> Select Name: intnet

* Create a VM in VirtualBox to act as bare metal. A VM with 1 CPU,
  1 GB memory should be sufficient. Let's name this VM as ``baremetal``.

* In VirtualBox Manager, Select ``baremetal`` VM -> Click Settings ->
  Network -> Adapter 1 -> Select 'Enable Network Adapter' ->
  Select Attached to: Internal Network -> Select Name: intnet

* Configure the VirtualBox web service to disable authentication. (This is
  only a suggestion. If you want, enable authentication with the appropriate
  web service authentication library.)

  ::

    VBoxManage setproperty websrvauthlibrary null

* Run VirtualBox web service::

    C:\Program Files\Oracle\VirtualBox\VBoxWebSrv.exe

* Power on the ``cloud-controller`` VM.

* All the following instructions are to be done in the ``cloud-controller`` VM.

* Install the GNU/Linux distribution of your choice.

* Set up devstack.

* Install pyremotevbox::

    sudo pip install "pyremotevbox>=0.5.0"

* Enable one (or more) of the VirtualBox drivers (``pxe_vbox``, ``agent_vbox``,
  or ``fake_vbox``) via the ``enabled_drivers`` configuration option in
  ``/etc/ironic/ironic.conf``, and restart Ironic conductor.

* Set up flat networking on ``eth1``. For details on how to do this, see
  :ref:`NeutronFlatNetworking`.

* Enroll a VirtualBox node. The following examples use the ``pxe_vbox``
  driver.

  ::

    ironic node-create -d pxe_vbox -i virtualbox_host='10.0.2.2' -i virtualbox_vmname='baremetal'

  If you are using authentication with VirtualBox web service, your username
  and password need to be provided. The ironic node-create command will look
  like::

    ironic node-create -d pxe_vbox -i virtualbox_host='10.0.2.2' -i virtualbox_vmname='baremetal' -i virtualbox_username=<username> -i virtualbox_password=<password>

  If VirtualBox web service is listening on a different port than the default
  18083, then that port may be specified using the driver_info
  parameter ``virtualbox_port``.

* Add other Node properties and trigger provisioning on the bare metal node.

  .. note::
    When a newly created bare metal VM is powered on for the first time by
    Ironic (during provisioning), VirtualBox will automatically pop up a
    dialog box asking to 'Select start-up disk'. Just press 'Cancel' to
    continue booting the VM.
