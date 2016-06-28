.. _inspection:

===================
Hardware Inspection
===================

Overview
--------

Inspection allows Bare Metal service to discover required node properties
once required ``driver_info`` fields (for example, IPMI credentials) are set
by an operator. Inspection will also create the Bare Metal service ports for the
discovered ethernet MACs. Operators will have to manually delete the Bare Metal
service ports for which physical media is not connected. This is required due
to the `bug 1405131 <https://bugs.launchpad.net/ironic/+bug/1405131>`_.

There are two kinds of inspection supported by Bare Metal service:

#. Out-of-band inspection is currently implemented by iLO drivers, listed at
   :ref:`ilo`.

#. `In-band inspection`_ by utilizing the ironic-inspector_ project.

Inspection can be initiated using node-set-provision-state.
The node should be in MANAGEABLE state before inspection is initiated.

* Move node to manageable state::

    ironic node-set-provision-state <node_UUID> manage

* Initiate inspection::

    ironic node-set-provision-state <node_UUID> inspect

.. note::
    The above commands require the python-ironicclient_ to be version 0.5.0 or greater.

.. _capabilities-discovery:

Capabilities discovery
----------------------

This is an incomplete list of capabilities we want to discover during
inspection. The exact support is driver-specific though, the most complete
list is provided by the iLO :ref:`ilo-inspection`.

``secure_boot`` (``true`` or ``false``)
    whether secure boot is supported for the node

``boot_mode`` (``bios`` or ``uefi``)
    the boot mode the node is using

``cpu_vt`` (``true`` or ``false``)
    whether the CPU virtualization is enabled

``cpu_aes`` (``true`` or ``false``)
    whether the AES CPU extensions are enabled

``max_raid_level`` (integer, 0-10)
    maximum RAID level supported by the node

``pci_gpu_devices`` (non-negative integer)
    number of GPU devices on the node

The operator can specify these capabilities in nova flavor for node to be selected
for scheduling::

  nova flavor-key my-baremetal-flavor set capabilities:pci_gpu_devices="> 0"

  nova flavor-key my-baremetal-flavor set capabilities:secure_boot="true"

Please see a specific driver page for the exact list of capabilities this
driver can discover.

In-band inspection
------------------

In-band inspection involves booting a ramdisk on the target node and fetching
information directly from it. This process is more fragile and time-consuming
than the out-of-band inspection, but it is not vendor-specific and works
across a wide range of hardware. In-band inspection is using the
ironic-inspector_ project.

Currently it is supported by the following generic drivers::

    pxe_ipmitool
    pxe_ipminative
    pxe_ssh
    agent_ipmitool
    agent_ipminative
    agent_ssh
    fake_inspector

It is also the default inspection approach for the following vendor drivers::

    pxe_drac
    pxe_ucs
    pxe_cimc
    agent_ucs
    agent_cimc

This feature needs to be explicitly enabled in the ironic configuration file
by setting ``enabled = True`` in ``[inspector]`` section.
You must additionally install python-ironic-inspector-client_ to use
this functionality.
You must set ``service_url`` if the ironic-inspector service is
being run on a separate host from the ironic-conductor service, or is using
non-standard port.

In order to ensure that ports in Bare Metal service are synchronized with
NIC ports on the node, the following settings in the ironic-inspector
configuration file must be set::

    [processing]
    add_ports = all
    keep_ports = present

.. note::
    During Kilo cycle we used an older version of Inspector called
    ironic-discoverd_. Inspector is expected to be a mostly drop-in
    replacement, and the same client library should be used to connect to both.

    For Kilo, install ironic-discoverd_ of version 1.1.0 or higher
    instead of python-ironic-inspector-client and use ``[discoverd]`` option
    group in both Bare Metal service and ironic-discoverd configuration
    files instead of ones provided above.

.. _ironic-inspector: https://pypi.python.org/pypi/ironic-inspector
.. _ironic-discoverd: https://pypi.python.org/pypi/ironic-discoverd
.. _python-ironic-inspector-client: https://pypi.python.org/pypi/python-ironic-inspector-client
.. _python-ironicclient: https://pypi.python.org/pypi/python-ironicclient
