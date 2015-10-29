.. _drivers:

=================
Enabling drivers
=================

Ironic-Python-Agent (agent)
---------------------------

To enable IPA, add the appropriate ironic agent driver to the ``enabled_drivers``
line of the ironic.conf file.

Several variants are currently supported, they are:
    * agent_ilo
    * agent_ipmitool
    * agent_pyghmi
    * agent_ssh
    * agent_vbox

.. note:: Starting with the Kilo release IPA ramdisk may also be used with ironic PXE drivers.

For more information see the `ironic-python-agent GitHub repo <https://github.com/openstack/ironic-python-agent/>`_

DRAC
----

DRAC with PXE deploy
^^^^^^^^^^^^^^^^^^^^

- Add ``pxe_drac`` to the list of ``enabled_drivers`` in
  ``/etc/ironic/ironic.conf``
- Install openwsman-python package

AMT
----

.. toctree::
  :maxdepth: 1

  ../drivers/amt

SNMP
----

.. toctree::
  :maxdepth: 1

  ../drivers/snmp

iLO driver
----------

.. toctree::
  :maxdepth: 1

  ../drivers/ilo

SeaMicro driver
---------------

.. toctree::
  :maxdepth: 1

  ../drivers/seamicro

iRMC
----

.. toctree::
  :maxdepth: 1

  ../drivers/irmc

VirtualBox drivers
------------------

.. toctree::
  :maxdepth: 1

  ../drivers/vbox


Cisco UCS driver
----------------

.. toctree::
  :maxdepth: 1

  ../drivers/ucs


Wake-On-Lan driver
------------------

.. toctree::
  :maxdepth: 1

  ../drivers/wol


iBoot driver
------------

.. toctree::
  :maxdepth: 1

  ../drivers/iboot


CIMC driver
------------

.. toctree::
  :maxdepth: 1

  ../drivers/cimc


OneView driver
--------------

.. toctree::
  :maxdepth: 1

  ../drivers/oneview


XenServer ssh driver
--------------------

.. toctree::
  :maxdepth: 1

  ../drivers/xenserver
