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

There are two AMT drivers:

* ``pxe_amt`` uses AMT for power management and deploys the user image over
  iSCSI from the conductor

* ``agent_amt`` uses AMT for power management and deploys the user image
  directly to the node via HTTP.

Set up your environment
=======================
A detailed reference is available here, and a short guide follows below:

   https://software.intel.com/en-us/articles/intel-active-management-technology-start-here-guide-intel-amt-9#4.2

* Set up AMT Client

  * Choose a system which supports Intel AMT / vPro. Desktop and laptop systems
    that support this can often be identified by looking at the "Intel" tag for
    the word ``vPro``.

  * During boot, press Ctrl+P to enter Intel MEBx management.

  * Reset password -- default is ``admin``. The new password must contain at
    least one upper case letter, one lower case letter, one digit and one
    special character, and be at least eight characters.

  * Go to Intel AMT Configuration:

    * Enable all features under SOL/IDER/KVM section

    * Select User Consent and choose None (No password is needed)

    * Select Network Setup section and set IP

    * Activate Network Access

  * MEBx Exit

  * Restart and enable PXE boot in bios

* Install ``openwsman`` on servers where ``ironic-conductor`` is running:

  * Fedora/RHEL: ``openwsman-python``.

  * Ubuntu: ``python-openwsman``'s most recent version is 2.4.3 which
    is enough.

  * Or build it yourself from: https://github.com/Openwsman/openwsman

* Enable the ``pxe_amt`` or ``agent_amt`` driver by adding it to the
  configuration option ``enabled_drivers`` (typically located at
  ``/etc/ironic/ironic.conf``) and restart the ``ironic-conductor``
  process::

    service ironic-conductor restart

* Enroll an AMT node

* Specify these driver_info properties for the node: ``amt_password``,
   ``amt_address``, and ``amt_username``

* Boot an instance

.. note::
    It is recommended that nodes using the pxe_amt driver be deployed with the
    `local boot`_ option. This is because the AMT firmware currently has no
    support for setting a persistent boot device. Nodes deployed without the
    `local boot`_ option could fail to boot if they are restarted outside of
    Ironic's control (I.E. rebooted by a local user) because the node will
    not attempt to PXE / network boot the kernel, using `local boot`_ solves this
    known issue.

.. _`local boot`: http://docs.openstack.org/project-install-guide/baremetal/newton/advanced.html#local-boot-with-partition-images
