============
iDRAC driver
============

Overview
========
The integrated Dell Remote Access Controller (iDRAC_), is an out-of-band
management platform on Dell servers, and is supported directly by the
``idrac`` hardware type.  This driver uses the Dell Web Services for
Management (WSMAN) APIs to perform all of its functions.

iDRAC_ hardware is also supported by the standard ``ipmi`` hardware type,
though with a smaller feature set.

Key features of the Dell iDRAC:

* Inventory and Monitoring
* Configure and use virtual console and virtual media.
* Remotely configure storage devices attached to the system at run-time.
* Physical and virtual disk management
* RAID controller management
* PCIe SSD device management
* Apply the device settings immediately, at next system reboot, at a
  scheduled time, or as a pending operation to be applied as a
  batch as part of a single job.

Ironic Features
---------------

The hardware type ``idrac`` supports following Ironic interfaces:

* `Inspect Interface`_: Hardware Inspection
* `Management Interface`_:
* `Power Interface`_: Power management
* `RAID Interface`_: RAID controller and disk management
* `Vendor Interface`_: BIOS management


Enabling
--------

The ``idrac`` hardware type requires the ``python-dracclient`` library to be
installed, for example::

    sudo pip install 'python-dracclient>=1.3.0'

To enable the ``idrac`` hardware type, add the following to your
``/etc/ironic/ironic.conf``:

.. code-block:: ini

    [DEFAULT]
    enabled_hardware_types=idrac
    enabled_management_interfaces=idrac
    enabled_power_interfaces=idrac

To enable all optional features (inspection, RAID and vendor passthru), use
the following configuration:

.. code-block:: ini

    [DEFAULT]
    enabled_hardware_types=idrac
    enabled_inspect_interfaces=idrac
    enabled_management_interfaces=idrac
    enabled_power_interfaces=idrac
    enabled_raid_interfaces=idrac
    enabled_vendor_interfaces=idrac


Enrolling
---------

The following command will enroll a bare metal node with the ``idrac``
hardware type:

.. code-block:: bash

    openstack baremetal node create --driver idrac \
        --driver-info drac_address=http://drac.host \
        --driver-info drac_username=user \
        --driver-info drac_password=pa$$w0rd


Inspect Interface
=================

The Dell iDrac out-of-band inspection process catalogs all the same
attributes of the server as the IPMI driver.  Unlike IMPI, it does this
without requiring the system to be rebooted, or even in a power on
state.  Inspection is performed using the Dell WSMAN API directly without
affecting the operation of the system being inspected.

The inspection discovers the following properties:

* ``cpu_arch``: cpu architecture
* ``cpus``: number of cpus
* ``local_gb``: disk size
* ``memory_mb``: memory size
* ``model``: the Dell server model (eg: "PowerEdge R640")
* ``provisioning_mac``: MAC address configured to PXE boot for provisioning.
* ``service_tag``: Dell service tag for the server (eg: "FL0AQD2")

Extra capabilities:

* ``boot_mode``: eufi or bios boot mode.
* ``boot_option``: ?
* ``cpu_aes``: true if the CPU supports AES encryption.
* ``cpu_hugepages``: true, if the CPU supports huge pages.
* ``cpu_hugepages_1g``: true if the CPU supports 1g huge pages.
* ``cpu_txt``: true if the CPU supports ?
* ``cpu_vt``: true, if the CPU supports cpu virtualization.

It also creates baremetal ports for each NIC card detected in the system.


Management Interface
====================

The following management functions are supported:

* `Set boot device`_
* `Show boot device`_

.. NOTE:
  Inject NMI is not supported.


Set Boot Device
---------------

``todo``

Show Boot Device
----------------

Returns a map of the boot device and persistent state of the device.

UEFI Secure Boot Support
------------------------

``todo``: Need more information about UEFI here.

See section on vendor passthrough


Power Interface
===============

The following power methods are supported:

* `Power off`_
* `Power on`_
* `Reboot`_

Power Off
---------

Transitions directly to a power off state (ACPI G2/S5).  Does not
request running Operating System to shut down cleanly first.  Does
not perform any action if the server is already powered off.

Power On
--------

Performs a direct power on operation of the server. Does not perform
any action if the server is already powered on.

Reboot
------

Transitions directly to a power off state (ACPI G2/S5), followed by a
transition to power on (ACPI G0/S0).  Does not request running Operating
System to shut down cleanly first.  Causes the system to boot regardless
of existing power state.


RAID Interface
==============

See :doc:`/admin/raid` for more information on Ironic RAID support.

The following propeties are supported by the iDrac RAID driver:


Mandatory properties
--------------------

* ``size_gb``: Size in GiB (Integer) for the logical disk. Use 'MAX' as size_gb if this logical disk is supposed to use the rest of the space available.
* ``raid_level``: RAID level for the logical disk. Valid values are
  '0', '1', '5', '6', '1+0', '5+0' and '6+0'.

.. NOTE::
  'JBOD' and '2' are not supported, and will fail with reason: Cannot
  calculate spans for RAID level.

Optional properties
-------------------

* ``is_root_volume``: Optional. Specifies whether this disk is a root volume. By default, this is False.
* ``volume_name``: Optional. Name of the volume to be created. If this is not specified, it will be auto-generated.

Backing physical disk hints
---------------------------

.. NOTE::
  These properties are currently not supported by the iDrac RAID driver.

* ``disk_type``
* ``interface_type``
* ``share_physical_disks``
* ``number_of_physical_disks``

Backing physical disks
----------------------

These are Dell RAID controller specific values and must match the
names as provided by the iDrac.

* ``controller``: Manditory. The name of the controller to use.
* ``physical_disks``: Manditory. The names of the physical disks to use.

Examples
--------

Creation of RAID 1+0 logical disk with 6 disks on one controller:

.. code-block:: json

  { "logical_disks":
    [ { "controller": "RAID.Integrated.1-1",
        "is_root_volume": "True",
        "physical_disks": [
          "Disk.Bay.0:Enclosure.Internal.0-1:RAID.Integrated.1-1",
          "Disk.Bay.1:Enclosure.Internal.0-1:RAID.Integrated.1-1",
          "Disk.Bay.2:Enclosure.Internal.0-1:RAID.Integrated.1-1",
          "Disk.Bay.3:Enclosure.Internal.0-1:RAID.Integrated.1-1",
          "Disk.Bay.4:Enclosure.Internal.0-1:RAID.Integrated.1-1",
          "Disk.Bay.5:Enclosure.Internal.0-1:RAID.Integrated.1-1"],
        "raid_level": "1+0",
        "size_gb": "MAX"}]}


Manual RAID Invocation
----------------------

The following command can be used to delete any existing RAID configuration:

.. code-block:: bash

  openstack baremetal node clean --clean-steps \
    '[{"interface": "raid", "step": "delete_configuration"}]' ${node_uuid}


The follwing command shows an example of how to set the target RAID configuration:

.. code-block:: bash

  openstack baremetal node set --target-raid-config '{ "logical_disks":
    [ { "controller": "RAID.Integrated.1-1",
        "is_root_volume": true,
        "physical_disks": [
          "Disk.Bay.0:Enclosure.Internal.0-1:RAID.Integrated.1-1",
          "Disk.Bay.1:Enclosure.Internal.0-1:RAID.Integrated.1-1"],
        "raid_level": "0",
        "size_gb": "MAX"}]}' ${node_uuid}


The following command can be used to create a RAID configuration:

.. code-block:: bash

  openstack baremetal node clean --clean-steps \
    '[{"interface": "raid", "step": "create_configuration"}]' ${node_uuid}


In the case where the physical disk names, or controller names are not
known, the following python code example shows how the python-dracclient
can be used to fetch the information directly from the Dell server:

.. code-block:: python

  import dracclient.client


  client = dracclient.client.DRACClient(
      host="192.168.1.1",
      username="root",
      password="calvin")
  controllers = client.list_raid_controllers()
  print (controllers)

  physical_disks = client.list_physical_disks()
  print (physical_disks)


Vendor  Interface
=================

Dell iDrac BIOS management is available through the Ironic vendor
passthrough interface.  The

====================  ============   ====================================
Method Name           HTTP Method    Descrption
====================  ============   ====================================
abandon_bios_config   DELETE         Abandon a BIOS configuration job
commit_bios_config    POST           Commit a BIOS configuration job
                                     submitted through set_bios_config.
                                     Required argument: 'reboot' -
                                     indicates whether a reboot job
                                     should be automatically created
                                     with the config job. Returns a
                                     dictionary containing the ``job_id``
                                     key with the ID of the newly created
                                     config job, and the ``reboot_required``
                                     key indicating whether the node needs
                                     to be rebooted to start the config job.
get_bios_config       GET            Returns a dictionary containing
                                     the BIOS settings from a node.
list_unfinished_jobs  GET            Returns a dictionary containing
                                     the key ``unfinished_jobs``; its value
                                     is a list of dictionaries. Each
                                     dictionary represents an unfinished
                                     config Job object.
set_bios_config       POST           Change the BIOS configuration on
                                     a node. Required argument: a
                                     dictionary of {``AttributeName``:
                                     ``NewValue``}. Returns a dictionary
                                     containing the 'commit_required'
                                     key with a Boolean value indicating
                                     whether commit_bios_config needs to
                                     be called to make the changes.
====================  ============   ====================================


Examples
--------

Get BIOS Config
~~~~~~~~~~~~~~~

.. code-block:: bash

  openstack baremetal node passthru call --http-method GET ${node_uuid} get_bios_config

Snippet of output showing virtualization enabled:

.. code-block:: json

  {"ProcVirtualization": {
        "current_value": "Disabled",
        "instance_id": "BIOS.Setup.1-1:ProcVirtualization",
        "name": "ProcVirtualization",
        "pending_value": null,
        "possible_values": [
            "Enabled",
            "Disabled"],
        "read_only": false }}

There are a number of items to note from the above snippet:

* ``name``: this is the name to use in a call to set_bios_config.
* ``current_value``: the current state of the setting.
* ``pending_value``: if the value has been set, but not yet committed,
  the new value is shown here.  The change can either be commited or
  abandoned.
* ``possible_values``: shows a list of valid values that can be used
  in a call to set_bios_config.
* ``read_only``: indicates if the value is capable of being changed.

Set BIOS Config
~~~~~~~~~~~~~~~

.. code-block:: bash

  openstack baremetal node passthru call ${node_uuid} set_bios_config --arg "name=value"


Walkthough of perfoming a BIOS configuration change:

The following section demonstrates how to change BIOS configuration settings,
detect that a commit and reboot are required, and act on them accordingly.  The
two properties that are being changed are:

* Enable virtualization technology of the processor
* Globally enable SR-IOV

.. code-block:: bash

  openstack baremetal node passthru call ${node_uuid} set_bios_config \
    --arg "ProcVirtualization=Enabled" \
    --arg "SriovGlobalEnable=Enabled"

This returns a dictionary indicating what actions are required next:

.. code-block:: json

	{
	    "is_reboot_required": true,
	    "commit_required": true,
	    "is_commit_required": true
	}

Commit BIOS Changes
~~~~~~~~~~~~~~~~~~~

Next step is to commit the pending change to the BIOS.  Note that in this
example, the ``reboot`` argument is set to true.  The response indicates
that a reboot is no longer required as it has been scheduled automatically
by the commit_bios_config call.  If the reboot argument is not supplied,
the job is still created, however it remains in the ``scheduled`` state
until a reboot is performed.  The reboot can be initiated through the
ironic reboot api.

.. code-block:: bash

  openstack baremetal node passthru call ${node_uuid} commit_bios_config \
    --arg "reboot=true"


.. code-block:: json

  {
      "job_id": "JID_499377293428",
      "reboot_required": false
  }

The state of any executing jobs can be queried:

.. code-block:: bash

  openstack baremetal node passthru call --http-method GET ${node_uuid} list_unfinished_jobs


.. code-block:: json

  {"unfinished_jobs":
      [{"status": "Scheduled",
        "name": "ConfigBIOS:BIOS.Setup.1-1",
        "until_time": "TIME_NA",
        "start_time": "TIME_NOW",
        "message": "Task successfully scheduled.",
        "percent_complete": "0",
        "id": "JID_499377293428"}]}


Adandon BIOS Changes
~~~~~~~~~~~~~~~~~~~~

Instead of committing, the pending change can also be rolled back
with an abandon command:

.. code-block:: bash

  openstack baremetal node passthru call --http-method DELETE ${node_uuid} abandon_bios_config

The abandon command does not provide a response body.


Change Boot Mode
----------------
``todo``:

.. code-block:: json

    {"BootMode": {
        "current_value": "Uefi",
        "instance_id": "BIOS.Setup.1-1:BootMode",
        "name": "BootMode",
        "pending_value": null,
        "possible_values": [
            "Bios",
            "Uefi"
        ],
        "read_only": false
    }}

.. code-block:: bash

  openstack baremetal node passthru call ${node_uuid} set_bios_config \
    --arg "BootMode=Uefi"

Known Issues
============

Nodes go into maintenance mode
------------------------------

After some period of time, nodes managed by the ``idrac`` hardware type may go
into maintenance mode in Ironic.  This issue can be worked around by changing
the Ironic power state poll interval to 70 seconds.  See
``[conductor]sync_power_state_interval`` in ``/etc/ironic/ironic.conf``.

.. _Ironic_RAID: https://docs.openstack.org/ironic/latest/admin/raid.html
.. _iDRAC: www.dell.com/idracmanuals
