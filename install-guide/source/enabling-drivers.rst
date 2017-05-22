Enabling drivers and hardware types
===================================

Introduction
------------

The Bare Metal service delegates actual hardware management to **drivers**.
Starting with the Ocata release, two types of drivers are supported:
*classic drivers* (for example, ``pxe_ipmitool``, ``agent_ilo``, etc.) and
the newer *hardware types* (for example, generic ``redfish`` and ``ipmi``
or vendor-specific ``ilo`` and ``irmc``).

Drivers, in turn, consist of *hardware interfaces*: sets of functionality
dealing with some aspect of bare metal provisioning in a vendor-specific way.
*Classic drivers* have all *hardware interfaces* hardcoded, while *hardware
types* only declare which *hardware interfaces* they are compatible with.

Please refer to the `driver composition reform specification`_
for technical details behind *hardware types*.

.. TODO(dtantsur): write devdocs on the driver composition and stop linking
                   to the specification.

From API user's point of view, both *classic drivers* and *hardware types* can
be assigned to the ``driver`` field of a node. However, they are configured
differently.

Enabling hardware types
-----------------------

Hardware types are enabled in the configuration file of the
**ironic-conductor** service by setting the ``enabled_hardware_types``
configuration option, for example:

.. code-block:: ini

    [DEFAULT]
    enabled_hardware_types = ipmi,redfish

However, due to their dynamic nature, they also require configuring enabled
hardware interfaces.

.. note::
   All available hardware types and interfaces are listed in setup.cfg_ file
   in the source code tree.

There are several types of hardware interfaces:

boot
    manages booting of both the deploy ramdisk and the user instances on the
    bare metal node. Boot interface implementations are often vendor specific,
    and can be enabled via the ``enabled_boot_interfaces`` option:

    .. code-block:: ini

        [DEFAULT]
        enabled_hardware_types = ipmi,ilo
        enabled_boot_interfaces = pxe,ilo-virtual-media

    Boot interfaces with ``pxe`` in their name require :doc:`configure-pxe`.
console
    manages access to the serial console of a bare metal node.
    See `Configuring Web or Serial Console`_ for details.
deploy
    defines how the image gets transferred to the target disk.

    * With ``iscsi`` deploy method the deploy ramdisk publishes node's hard
      drive as an iSCSI_ share. The ironic-conductor then copies the image
      to this share. Requires :doc:`configure-iscsi`.

    * With ``direct`` deploy method, the deploy ramdisk fetches the image
      from an HTTP location (object storage temporary URL or user-provided
      HTTP URL).

    .. code-block:: ini

        [DEFAULT]
        enabled_hardware_types = ipmi,redfish
        enabled_deploy_interfaces = iscsi,direct
inspect
    implements fetching hardware information from nodes. Can be implemented
    out-of-band (via contacting the node's BMC) or in-band (via booting
    a ramdisk on a node). The latter implementation is called ``inspector``
    and uses a separate service called ironic-inspector_. Example:

    .. code-block:: ini

        [DEFAULT]
        enabled_hardware_types = ipmi,ilo,irmc
        enabled_inspect_interfaces = ilo,irmc,inspector

    See `inspection documentation`_ for more details.
management
    provides additional hardware management actions, like getting or setting
    boot devices. This interface is usually vendor-specific, and its name
    often matches the name of the hardware type (with ``ipmitool`` being
    a notable exception). For example:

    .. code-block:: ini

        [DEFAULT]
        enabled_hardware_types = ipmi,redfish,ilo,irmc
        enabled_management_interfaces = ipmitool,redfish,ilo,irmc

    Using ``ipmitool`` requires :doc:`configure-ipmi`. See
    `driver-specific documentation`_ for required configuration of each driver.
network
    connects/disconnects bare metal nodes to/from virtual networks. This is
    the only interface that is also pluggable for classic drivers. See
    :doc:`configure-tenant-networks` for more details.
power
    runs power actions on nodes. Similar to the management interface, it is
    usually vendor-specific, and its name often matches the name of the
    hardware type (with ``ipmitool`` being again an exception). For example:

    .. code-block:: ini

        [DEFAULT]
        enabled_hardware_types = ipmi,redfish,ilo,irmc
        enabled_power_interfaces = ipmitool,redfish,ilo,irmc

    Using ``ipmitool`` requires :doc:`configure-ipmi`. See
    `driver-specific documentation`_ for required configuration of each driver.
raid
    manages building and tearing down RAID on nodes. Similar to inspection,
    it can be implemented either out-of-band or in-band (via ``agent``
    implementation). See `RAID documentation`_ for details.

    .. code-block:: ini

        [DEFAULT]
        enabled_hardware_types = ipmi,redfish,ilo,irmc
        enabled_raid_interfaces = agent,no-raid
vendor
    is a place for vendor extensions to be exposed in API. See `vendor
    methods documentation`_ for details.

    .. code-block:: ini

        [DEFAULT]
        enabled_hardware_types = ipmi,redfish,ilo,irmc
        enabled_vendor_interfaces = ipmitool,no-vendor

Here is a complete configuration example, enabling two generic protocols,
IPMI and Redfish, with a few additional features:

.. code-block:: ini

    [DEFAULT]
    enabled_hardware_types = ipmi,redfish
    enabled_boot_interfaces = pxe
    enabled_console_interfaces = ipmitool-socat,no-console
    enabled_deploy_interfaces = iscsi,direct
    enabled_inspect_interfaces = inspector
    enabled_management_interfaces = ipmitool,redfish
    enabled_network_interfaces = flat,neutron
    enabled_power_interfaces = ipmitool,redfish
    enabled_raid_interfaces = agent
    enabled_vendor_interfaces = ipmitool,no-vendor

Note that some interfaces have implementations named ``no-<TYPE>`` where
``<TYPE>`` is the interface type. These implementations do nothing and return
errors when used from API.

.. TODO(dtantsur): create dev documentation on defaults calculation, and link
   it here. Add explanation of default_<NAME>_interface options.

Enabling classic drivers
------------------------

Classic drivers are enabled in the configuration file of the
**ironic-conductor** service by setting the ``enabled_drivers`` configuration
option, for example:

.. code-block:: ini

    [DEFAULT]
    enabled_drivers = pxe_ipmitool,pxe_ilo,pxe_drac

The names in this comma-separated list are entry point names of the drivers.
They have to be available at conductor start-up, and all dependencies must
be installed locally. For example,

* drivers starting with ``pxe`` and some drivers starting with ``agent``
  require :doc:`configure-pxe`,

* drivers starting with ``pxe`` or having ``iscsi`` in their name require
  :doc:`configure-iscsi`,

* drivers ending with ``ipmitool`` require :doc:`configure-ipmi`.

See `driver-specific documentation`_ for required configuration of each driver.

.. _driver composition reform specification: http://specs.openstack.org/openstack/ironic-specs/specs/approved/driver-composition-reform.html
.. _driver-specific documentation: https://docs.openstack.org/developer/ironic/deploy/drivers.html
.. _setup.cfg: https://git.openstack.org/cgit/openstack/ironic/tree/setup.cfg
.. _`Configuring Web or Serial Console`: http://docs.openstack.org/developer/ironic/deploy/console.html
.. _iSCSI: https://en.wikipedia.org/wiki/ISCSI
.. _ironic-inspector: https://docs.openstack.org/developer/ironic-inspector/
.. _inspection documentation: https://docs.openstack.org/developer/ironic/deploy/inspection.html
.. _RAID documentation: https://docs.openstack.org/developer/ironic/deploy/raid.html
.. _vendor methods documentation: https://docs.openstack.org/developer/ironic/dev/vendor-passthru.html
