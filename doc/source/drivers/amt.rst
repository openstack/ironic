.. _amt:

===========
AMT drivers
===========

Overview
========
AMT (Active Management Technology) drivers extend Ironic's range to the
desktop. AMT/vPro is widely used in desktops to remotely control their power,
similar to IPMI in servers.

AMT drivers use WS-MAN protocol to interact with AMT clients.
They work on AMT 7.0/8.0/9.0. AMT 7.0 was released in 2010, so AMT drivers
should work on most PCs with vPro.

There is one AMT driver:

* ``pxe_amt`` uses AMT for power management and PXE for deploy management.

Set up your environment
=======================
* Set up AMT Client

  * Choose a Desktop with ``vPro`` tag (within Intel's tag, next to CORE i5/7).
    Press Ctrl+P during booting to enter MEBx management.

  * Reset password -- default is ``admin``. New password can be ``Cloud12345^``

  * Go to Intel AMT Configuration:

    * Enable all features under SOL/IDER/KVM section

    * Select User Consent and choose None (No password is needed)

    * Select Network Setup section and set IP

    * Activate Network Access

  * MEBx Exit

  * Restart and enable PXE boot in bios

* Install ``openwsman`` on servers where ``ironic-conductor`` is running:

  * Fedora/RHEL: ``openwsman-python`` (>=2.4.10). You can 
    get the RPM package for Fedora 20 from::

    http://download.opensuse.org/repositories/Openwsman/Fedora_20/

  * Ubuntu: ``python-openwsman``'s most recent version is 2.4.3 which
    isn't recent enough, so you'll need to build it yourself (see next point)

  * Or build it yourself from::

    https://github.com/Openwsman/openwsman

* Enable the ``pxe_amt`` driver by adding it to the configuration option
  ``enabled_drivers`` (typically located at ``/etc/ironic/ironic.conf``)
  and restart the ``ironic-conductor`` process::

  service ironic-conductor restart

* Enroll an AMT node

* Specify these driver_info properties for the node: ``amt_password``,
   ``amt_address``, and ``amt_username``

* Boot an instance
