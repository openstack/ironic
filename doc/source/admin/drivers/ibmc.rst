===============
iBMC driver
===============

Overview
========

The ``ibmc`` driver is targeted for Huawei V5 series rack server such as
2288H V5, CH121 V5. The iBMC hardware type enables the user to take advantage
of features of `Huawei iBMC`_ to control Huawei server.

The ``ibmc`` hardware type supports the following Ironic interfaces:

* Management Interface: Boot device management
* Power Interface: Power management
* `RAID Interface`_: RAID controller and disk management
* `Vendor Interface`_: ibmc passthru interfaces

Prerequisites
=============

The `HUAWEI iBMC Client library`_ should be installed on the ironic conductor
  node(s).

For example, it can be installed with ``pip``::

    sudo pip install python-ibmcclient

Enabling the iBMC driver
============================

#. Add ``ibmc`` to the list of ``enabled_hardware_types``,
   ``enabled_power_interfaces``, ``enabled_vendor_interfaces``
   and ``enabled_management_interfaces`` in ``/etc/ironic/ironic.conf``. For example::

    [DEFAULT]
    ...
    enabled_hardware_types = ibmc
    enabled_power_interfaces = ibmc
    enabled_management_interfaces = ibmc
    enabled_raid_interfaces = ibmc
    enabled_vendor_interfaces = ibmc

#. Restart the ironic conductor service::

    sudo service ironic-conductor restart

    # Or, for RDO:
    sudo systemctl restart openstack-ironic-conductor

Registering a node with the iBMC driver
===========================================

Nodes configured to use the driver should have the ``driver`` property
set to ``ibmc``.

The following properties are specified in the node's ``driver_info``
field:

- ``ibmc_address``:

  The URL address to the ibmc controller. It must
  include the authority portion of the URL, and can
  optionally include the scheme. If the scheme is
  missing, https is assumed.
  For example: https://ibmc.example.com. This is required.

- ``ibmc_username``:

  User account with admin/server-profile access
  privilege. This is required.

- ``ibmc_password``:

  User account password. This is required.

- ``ibmc_verify_ca``:

  If ibmc_address has the **https** scheme, the
  driver will use a secure (TLS_) connection when
  talking to the ibmc controller. By default
  (if this is set to True), the driver will try to
  verify the host certificates. This can be set to
  the path of a certificate file or directory with
  trusted certificates that the driver will use for
  verification. To disable verifying TLS_, set this
  to False. This is optional.

The ``baremetal node create`` command can be used to enroll
a node with the ``ibmc`` driver. For example:

.. code-block:: bash

  baremetal node create --driver ibmc
    --driver-info ibmc_address=https://example.com \
    --driver-info ibmc_username=admin \
    --driver-info ibmc_password=password

For more information about enrolling nodes see :ref:`enrollment`
in the install guide.

RAID Interface
==============

Currently, only RAID controller which supports OOB management can be managed.

See :doc:`/admin/raid` for more information on Ironic RAID support.

The following properties are supported by the iBMC raid interface
implementation, ``ibmc``:

Mandatory properties
--------------------

* ``size_gb``: Size in gigabytes (integer) for the logical disk. Use ``MAX`` as
  ``size_gb`` if this logical disk is supposed to use the rest of the space
  available.
* ``raid_level``: RAID level for the logical disk. Valid values are
  ``JBOD``, ``0``, ``1``, ``5``, ``6``, ``1+0``, ``5+0`` and ``6+0``. And it
  is possible that some RAID controllers can only support a subset RAID
  levels.

.. NOTE::
  RAID level ``2`` is not supported by ``iBMC`` driver.

Optional properties
-------------------

* ``is_root_volume``: Optional. Specifies whether this disk is a root volume.
  By default, this is ``False``.
* ``volume_name``: Optional. Name of the volume to be created. If this is not
  specified, it will be N/A.

Backing physical disk hints
---------------------------

See :doc:`/admin/raid` for more information on backing disk hints.

These are machine-independent properties. The hints are specified for each
logical disk to help Ironic find the desired disks for RAID configuration.

* ``share_physical_disks``
* ``disk_type``
* ``interface_type``
* ``number_of_physical_disks``

Backing physical disks
----------------------

These are HUAWEI RAID controller dependent properties:

* ``controller``: Optional. Supported values are: RAID storage id,
  RAID storage name or RAID controller name. If a bare metal server have more
  than one controller, this is mandatory. Typical values would look like:

    * RAID Storage Id: ``RAIDStorage0``
    * RAID Storage Name: ``RAIDStorage0``
    * RAID Controller Name: ``RAID Card1 Controller``.

* ``physical_disks``: Optional. Supported values are: disk-id, disk-name or
  disk serial number. Typical values for hdd disk would look like:

    * Disk Id: ``HDDPlaneDisk0``
    * Disk Name: ``Disk0``.
    * Disk SerialNumber: ``38DGK77LF77D``

Delete RAID configuration
-------------------------

For ``delete_configuration`` step, ``ibmc`` will do:

* delete all logical disks
* delete all hot-spare disks

Logical disks creation priority
-------------------------------

Logical Disks creation priority based on three properties:

* ``share_physical_disks``
* ``physical_disks``
* ``size_gb``

The logical disks creation priority strictly follow the table below, if
multiple logical disks have the same priority, then they will be created with
the same order in ``logical_disks`` array.

====================       ==========================       =========
Share physical disks       Specified Physical Disks         Size
====================       ==========================       =========
no                         yes                              int|max
no                         no                               int
yes                        yes                              int
yes                        yes                              max
yes                        no                               int
yes                        no                               max
no                         no                               max
====================       ==========================       =========

Physical disks choice strategy
------------------------------

.. note::
    physical-disk-group: a group of physical disks which have been used by some
    logical-disks with same RAID level.


*   If no ``physical_disks`` are specified, the "waste least" strategy will be
    used to choose the physical disks.

    * waste least disk capacity: when using disks with different capacity, it
      will cause a waste of disk capacity. This is to avoid with highest
      priority.
    * using least total disk capacity: for example, we can create 400G RAID 5
      with both 5 100G-disks and 3 200G-disks. 5 100G disks is a better
      strategy because it uses a 500G capacity totally. While 3 200G-disks
      are 600G totally.
    * using least disk count: finally, if waste capacity and total disk
      capacity are both the same (it rarely happens?), we will choose the one
      with the minimum number of disks.

*   when ``share_physical_disks`` option is present, ``ibmc`` driver will
    create logical disk upon existing physical-disk-group list first. Only
    when no existing physical-disk-group matches, then it chooses unused
    physical disks with same strategy described above. When multiple exists
    physical-disk-groups matches, it will use "waste least" strategy too,
    the bigger capacity left the better. For example, to create a logical disk
    shown below on a ``ibmc`` server which has two RAID5 logical disks already.
    And the shareable capacity of this two logical-disks are 500G and 300G,
    then ``ibmc`` driver will choose the second one.

    .. code-block:: json

     {
        "logical_disks": [
            {
                "controller": "RAID Card1 Controller",
                "raid_level": "5",
                "size_gb": 100,
                "share_physical_disks": true
            }
        ]
     }

    And the ``ibmc`` server has two RAID5 logical disks already.

*   When ``size_gb`` is set to ``MAX``, ``ibmc`` driver will auto work through
    all possible cases and choose the "best" solution which has the biggest
    capacity and use least capacity. For example: to create a RAID 5+0 logical
    disk with MAX size in a server has 9 200G-disks, it will finally choose
    "8 disks + span-number 2" but not "9 disks + span-number 3". Although they
    both have 1200G capacity totally, but the former uses only 8 disks and the
    latter uses 9 disks. If you want to choose the latter solution, you can
    specified the disk count to use by adding ``number_of_physical_disks``
    option.

    .. code-block:: json

     {
        "logical_disks": [
            {
                "controller": "RAID Card1 Controller",
                "raid_level": "5+0",
                "size_gb": "MAX"
            }
        ]
     }


Examples
--------

In a typical scenario we may want to create:
 * RAID 5, 500G, root OS volume with 3 disks
 * RAID 5, rest available space, data volume with rest disks

.. code-block:: json

  {
    "logical_disks": [
        {
            "volume_name": "os_volume",
            "controller": "RAID Card1 Controller",
            "is_root_volume": "True",
            "physical_disks": [
                "Disk0",
                "Disk1",
                "Disk2"
            ],
            "raid_level": "5",
            "size_gb": "500"
        },
        {
            "volume_name": "data_volume",
            "controller": "RAID Card1 Controller",
            "raid_level": "5",
            "size_gb": "MAX"
        }
    ]
  }

Vendor Interface
=========================================

The ``ibmc`` hardware type provides vendor passthru interfaces shown below:


========================  ============   ======================================
Method Name               HTTP Method    Description
========================  ============   ======================================
boot_up_seq               GET            Query boot up sequence
get_raid_controller_list  GET            Query RAID controller summary info
========================  ============   ======================================


PXE Boot and iSCSI Deploy Process with Ironic Standalone Environment
====================================================================

.. figure:: ../../images/ironic_standalone_with_ibmc_driver.svg
   :width: 960px
   :align: left
   :alt: Ironic standalone with iBMC driver node

.. _Huawei iBMC: https://e.huawei.com/en/products/cloud-computing-dc/servers/accessories/ibmc
.. _TLS: https://en.wikipedia.org/wiki/Transport_Layer_Security
.. _HUAWEI iBMC Client library: https://pypi.org/project/python-ibmcclient/
