.. _amt:

===========
AMT drivers
===========

Overview
========
Introduce new drivers AMT to extend Ironic's range to desktop.
AMT/vPro is widely used in desktop to remotely control the power,
similar like IPMI in server.

AMT driver use WS-MAN protocol to interactive with AMT client.
This works on AMT 7.0/8.0/9.0. AMT 7.0 is released on 2010, so most
PCs with vPro should be involved.

Currently there is one AMT driver:

* ``pxe_amt`` use amt as power management and pxe as deploy management.

Setting up development environment
==================================
* Set up AMT Client

  * Choose a Desktop with ``vPro`` tag(within Intel's tag, next to CORE i5/7) -
    Press Ctrl+P during booting to enter MEBx management

  * Reset password - Default is ``admin``. New password can be ``Cloud12345^``

  * Go to Intel AMT Configuration:

    * Enable all features under SOL/IDER/KVM section

    * Select User Consent and choose None(No password need)

    * Select Network Setup section and set IP

    * Activate Network Access

  * MEBx Exit

  * Restart and enable PXE boot in bios

* Install ``openwsman&openwsman-python(>=2.4.10)`` on Ironic Server

  Get the rpm package for fedora 20 from::

    http://download.opensuse.org/repositories/Openwsman/Fedora_20/

  Or build by yourself from::

    https://github.com/Openwsman/openwsman

* Enable ``pxe_amt`` in ``enabled_drivers`` in ``/etc/ironic/ironic.conf``
  and restart Ironic conductor

* Enroll a AMT node

* Add ``amt_password/amt_address/amt_username`` into driver_info

* Boot an instance
