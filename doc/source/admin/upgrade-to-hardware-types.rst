Upgrading to Hardware Types
===========================

Starting with the Rocky release, the Bare Metal service does not support
*classic drivers* any more. If you still use *classic drivers*, please
upgrade to *hardware types* immediately. Please see
:doc:`/install/enabling-drivers` for details on
*hardware types* and *hardware interfaces*.

Planning the upgrade
--------------------

It is necessary to figure out which hardware types and hardware interfaces
correspond to which classic drivers used in your deployment. The following
table lists the classic drivers with their corresponding hardware types and
the boot, deploy, inspect, management, and power hardware interfaces:

===================== ==================== ==================== ==============  ========== ========== =========
   Classic Driver        Hardware Type             Boot             Deploy       Inspect   Management   Power
===================== ==================== ==================== ==============  ========== ========== =========
agent_ilo             ilo                  ilo-virtual-media    direct          ilo        ilo        ilo
agent_ipmitool        ipmi                 pxe                  direct          inspector  ipmitool   ipmitool
agent_ipmitool_socat  ipmi                 pxe                  direct          inspector  ipmitool   ipmitool
agent_irmc            irmc                 irmc-virtual-media   direct          irmc       irmc       irmc
iscsi_ilo             ilo                  ilo-virtual-media    iscsi           ilo        ilo        ilo
iscsi_irmc            irmc                 irmc-virtual-media   iscsi           irmc       irmc       irmc
pxe_drac              idrac                pxe                  iscsi           idrac      idrac      idrac
pxe_drac_inspector    idrac                pxe                  iscsi           inspector  idrac      idrac
pxe_ilo               ilo                  ilo-pxe              iscsi           ilo        ilo        ilo
pxe_ipmitool          ipmi                 pxe                  iscsi           inspector  ipmitool   ipmitool
pxe_ipmitool_socat    ipmi                 pxe                  iscsi           inspector  ipmitool   ipmitool
pxe_irmc              irmc                 irmc-pxe             iscsi           irmc       irmc       irmc
pxe_snmp              snmp                 pxe                  iscsi           no-inspect fake       snmp
===================== ==================== ==================== ==============  ========== ========== =========

.. note::
    The ``inspector`` *inspect* interface was only used if
    explicitly enabled in the configuration. Otherwise, ``no-inspect``
    was used.

.. note::
    ``pxe_ipmitool_socat`` and ``agent_ipmitool_socat`` use
    ``ipmitool-socat`` *console* interface (the default for the ``ipmi``
    hardware type), while ``pxe_ipmitool`` and ``agent_ipmitool`` use
    ``ipmitool-shellinabox``. See Console_ for details.

For out-of-tree drivers you may need to reach out to their maintainers or
figure out the appropriate interfaces by researching the source code.

Configuration
-------------

You will need to enable hardware types and interfaces that correspond to your
currently enabled classic drivers. For example, if you have the following
configuration in your ``ironic.conf``:

.. code-block:: ini

    [DEFAULT]
    enabled_drivers = pxe_ipmitool,agent_ipmitool

You will have to add this configuration as well:

.. code-block:: ini

    [DEFAULT]
    enabled_hardware_types = ipmi
    enabled_boot_interfaces = pxe
    enabled_deploy_interfaces = iscsi,direct
    enabled_management_interfaces = ipmitool
    enabled_power_interfaces = ipmitool

.. note::
    For every interface type there is an option
    ``default_<INTERFACE>_interface``, where ``<INTERFACE>`` is the interface
    type name. For example, one can make all nodes use the ``direct`` deploy
    method by default by setting:

    .. code-block:: ini

        [DEFAULT]
        default_deploy_interface = direct

Migrating nodes
---------------

After the required items are enabled in the configuration, each node's
``driver`` field has to be updated to a new value. You may need to also
set new values for some or all interfaces:

.. code-block:: console

    export OS_BAREMETAL_API_VERSION=1.31

    for uuid in $(openstack baremetal node list --driver pxe_ipmitool -f value -c UUID); do
        openstack baremetal node set $uuid --driver ipmi --deploy-interface iscsi
    done

    for uuid in $(openstack baremetal node list --driver agent_ipmitool -f value -c UUID); do
        openstack baremetal node set $uuid --driver ipmi --deploy-interface direct
    done

See :doc:`/install/enrollment` for more details on setting hardware types and
interfaces.

.. warning::
    It is not recommended to change the interfaces for ``active`` nodes. If
    absolutely needed, the nodes have to be put in the maintenance mode first:

    .. code-block:: console

        openstack baremetal node maintenance set $UUID \
            --reason "Changing driver and/or hardware interfaces"
        # do the update, validate its correctness
        openstack baremetal node maintenance unset $UUID

Other interfaces
----------------

Care has to be taken to migrate from classic drivers using non-default
interfaces. This chapter covers a few of the most commonly used.

Ironic Inspector
~~~~~~~~~~~~~~~~

Some classic drivers, notably ``pxe_ipmitool``, ``agent_ipmitool`` and
``pxe_drac_inspector``, use ironic-inspector_ for their *inspect* interface.

The same functionality is available for all hardware types, but the appropriate
``inspect`` interface has to be enabled in the Bare Metal service configuration
file, for example:

.. code-block:: ini

    [DEFAULT]
    enabled_inspect_interfaces = inspector,no-inspect

See :doc:`/install/enabling-drivers` for more details.

.. note::
    The configuration option ``[inspector]enabled`` does not affect hardware
    types.

Then you can tell your nodes to use this interface, for example:

.. code-block:: console

    export OS_BAREMETAL_API_VERSION=1.31
    for uuid in $(openstack baremetal node list --driver ipmi -f value -c UUID); do
        openstack baremetal node set $uuid --inspect-interface inspector
    done

.. note::
    A node configured with the IPMI hardware type, will use the inspector
    inspection implementation automatically if it is enabled. This is not
    the case for the most of the vendor drivers.

.. _ironic-inspector: https://docs.openstack.org/ironic-inspector/

Console
~~~~~~~

Several classic drivers, notably ``pxe_ipmitool_socat`` and
``agent_ipmitool_socat``, use socat-based serial console implementation.

For the ``ipmi`` hardware type it is used by default, if enabled in the
configuration file:

.. code-block:: ini

    [DEFAULT]
    enabled_console_interfaces = ipmitool-socat,no-console

If you want to use the ``shellinabox`` implementation instead, it has to be
enabled as well:

.. code-block:: ini

    [DEFAULT]
    enabled_console_interfaces = ipmitool-shellinabox,no-console

Then you need to update some or all nodes to use it explicitly. For example,
to update all nodes use:

.. code-block:: console

    export OS_BAREMETAL_API_VERSION=1.31
    for uuid in $(openstack baremetal node list --driver ipmi -f value -c UUID); do
        openstack baremetal node set $uuid --console-interface ipmitool-shellinabox
    done

RAID
~~~~

Many classic drivers, including ``pxe_ipmitool`` and ``agent_ipmitool`` use
the IPA-based in-band RAID implementation by default.

For the hardware types it is not used by default. To use it, you need to
enable it in the configuration first:

.. code-block:: ini

    [DEFAULT]
    enabled_raid_interfaces = agent,no-raid

Then you can update those nodes that support in-band RAID to use the ``agent``
RAID interface. For example, to update all nodes use:

.. code-block:: console

    export OS_BAREMETAL_API_VERSION=1.31
    for uuid in $(openstack baremetal node list --driver ipmi -f value -c UUID); do
        openstack baremetal node set $uuid --raid-interface agent
    done

.. note::
    The ability of a node to use the ``agent`` RAID interface depends on
    the ramdisk (more specifically, a `hardware manager`_ used in it),
    not on the driver.

.. _hardware manager: https://docs.openstack.org/ironic-python-agent/latest/contributor/hardware_managers.html

Network and storage
~~~~~~~~~~~~~~~~~~~

The network and storage interfaces have always been dynamic, and thus do not
require any special treatment during upgrade.

Vendor
~~~~~~

Classic drivers are allowed to use the ``VendorMixin`` functionality
to combine and expose several node or driver vendor passthru methods
from different vendor interface implementations in one driver.

**This is no longer possible with hardware types.**

With hardware types, a vendor interface can only have a single active
implementation from the list of vendor interfaces supported by a given
hardware type.

Ironic no longer has in-tree drivers (both classic and hardware types) that
rely on this ``VendorMixin`` functionality support.
However if you are using an out-of-tree classic driver that depends on it,
you'll need to do the following in order to use vendor
passthru methods from different vendor passthru implementations:

#. While creating a new hardware type to replace your classic driver,
   specify all vendor interface implementations your classic driver
   was using to build its ``VendorMixin`` as supported vendor interfaces
   (property ``supported_vendor_interfaces`` of the Python class
   that defines your hardware type).
#. Ensure all required vendor interfaces are enabled in the ironic
   configuration file under the ``[DEFAULT]enabled_vendor_interfaces``
   option.
   You should also consider setting the ``[DEFAULT]default_vendor_interface``
   option to specify the vendor interface for nodes that do not have one set
   explicitly.
#. Before invoking a specific vendor passthru method,
   make sure that the node's vendor interface is set to the interface
   with the desired vendor passthru method.
   For example, if you want to invoke the vendor passthru method
   ``vendor_method_foo()`` from ``vendor_foo`` vendor interface:

     .. code-block:: shell

        # set the vendor interface to 'vendor_foo`
        openstack --os-baremetal-api-version 1.31 baremetal node set <node> --vendor-interface vendor_foo

        # invoke the vendor passthru method
        openstack baremetal node passthru call <node> vendor_method_foo
