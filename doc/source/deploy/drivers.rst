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

The iRMC driver enables PXE deploy to control power via ServerView Common
Command Interface (SCCI).

Software requirements
^^^^^^^^^^^^^^^^^^^^^

- Install `python-scciclient package <https://pypi.python.org/pypi/python-scciclient>`_::

  $ pip install "python-scciclient>=0.1.0"

Enabling the iRMC driver
^^^^^^^^^^^^^^^^^^^^^^^^

- Add ``pxe_irmc`` to the list of ``enabled_drivers in``
  ``/etc/ironic/ironic.conf``
- Ironic Conductor must be restarted for the new driver to be loaded.

Ironic node configuration
^^^^^^^^^^^^^^^^^^^^^^^^^

Nodes are configured for iRMC with PXE deploy by setting the ironic node
object's ``driver`` property to be ``pxe_irmc``.  Further configuration values
are added to ``driver_info``:

- ``irmc_address``: hostname or IP of iRMC
- ``irmc_username``: username for iRMC with administrator privileges
- ``irmc_password``: password for irmc_username
- ``irmc_port``: port number of iRMC (optional, either 80 or 443. defalut 443)
- ``irmc_auth_method``: authentication method for iRMC (optional, either
  'basic' or 'digest'. default is 'basic')

Supported platforms
^^^^^^^^^^^^^^^^^^^
This driver supports FUJITSU PRIMERGY BX S4 or RX S8 servers and above.

- PRIMERGY BX920 S4
- PRIMERGY BX924 S4
- PRIMERGY RX300 S8


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
