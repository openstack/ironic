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

.. _enable-hardware-types:

Enabling hardware types
-----------------------

Hardware types are enabled in the configuration file of the
**ironic-conductor** service by setting the ``enabled_hardware_types``
configuration option, for example:

.. code-block:: ini

    [DEFAULT]
    enabled_hardware_types = ipmi,redfish

Due to the driver's dynamic nature, they also require configuring enabled
hardware interfaces.

.. note::
   All available hardware types and interfaces are listed in setup.cfg_ file
   in the source code tree.

.. _enable-hardware-interfaces:

Enabling hardware interfaces
~~~~~~~~~~~~~~~~~~~~~~~~~~~~

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
    There are also a few hardware-specific boot interfaces - see
    :doc:`/admin/drivers` for their required configuration.
console
    manages access to the serial console of a bare metal node.
    See :doc:`/admin/console` for details.
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

    See :doc:`/admin/inspection` for more details.
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
    :doc:`/admin/drivers` for the required configuration of each driver.
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
    :doc:`/admin/drivers` for the required configuration of each driver.
raid
    manages building and tearing down RAID on nodes. Similar to inspection,
    it can be implemented either out-of-band or in-band (via ``agent``
    implementation). See :doc:`/admin/raid` for details. For example:

    .. code-block:: ini

        [DEFAULT]
        enabled_hardware_types = ipmi,redfish,ilo,irmc
        enabled_raid_interfaces = agent,no-raid
storage
    manages the interaction with a remote storage subsystem, such as the
    Block Storage service, and helps facilitate booting from a remote
    volume. This interface ensures that volume target and connector
    information is updated during the lifetime of a deployed instance.
    See :doc:`/admin/boot-from-volume` for more details.

    This interface defaults to a ``noop`` driver as it is considered
    an "opt-in" interface which requires additional configuration
    by the operator to be usable.

    For example:

    .. code-block:: ini

        [DEFAULT]
        enabled_hardware_types = ipmi,irmc
        enabled_storage_interfaces = cinder,noop

vendor
    is a place for vendor extensions to be exposed in API. See
    :doc:`/contributor/vendor-passthru` for details.

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
    enabled_storage_interfaces = cinder,noop
    enabled_vendor_interfaces = ipmitool,no-vendor

Note that some interfaces have implementations named ``no-<TYPE>`` where
``<TYPE>`` is the interface type. These implementations do nothing and return
errors when used from API.

Hardware interfaces in multi-conductor environments
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

When enabling hardware types and their interfaces, make sure that for
every enabled hardware type, the whole set of enabled interfaces matches for
all conductors. However, different conductors can have different hardware
types enabled.

For example, you can have two conductors with the following configuration
respectively:

.. code-block:: ini

    [DEFAULT]
    enabled_hardware_types = ipmi
    enabled_deploy_interfaces = direct
    enabled_power_interfaces = ipmitool
    enabled_management_interfaces = ipmitool

.. code-block:: ini

    [DEFAULT]
    enabled_hardware_types = redfish
    enabled_deploy_interfaces = iscsi
    enabled_power_interfaces = redfish
    enabled_management_interfaces = redfish

But you cannot have two conductors with the following configuration
respectively:

.. code-block:: ini

    [DEFAULT]
    enabled_hardware_types = ipmi,redfish
    enabled_deploy_interfaces = direct
    enabled_power_interfaces = ipmitool,redfish
    enabled_management_interfaces = ipmitool,redfish

.. code-block:: ini

    [DEFAULT]
    enabled_hardware_types = redfish
    enabled_deploy_interfaces = iscsi
    enabled_power_interfaces = redfish
    enabled_management_interfaces = redfish

This is because the ``redfish`` hardware type will have different enabled
*deploy* interfaces on these conductors. It would have been fine, if the second
conductor had ``enabled_deploy_interfaces = direct`` instead of ``iscsi``.

This situation is not detected by the Bare Metal service, but it can cause
inconsistent behavior in the API, when node functionality will depend on
which conductor it gets assigned to.

.. note::
   We don't treat this as an error, because such *temporary* inconsistency is
   inevitable during a rolling upgrade or a configuration update.

Configuring interface defaults
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

When an operator does not provide an explicit value for one of the interfaces
(when creating a node or updating its driver), the default value is calculated
as described in :ref:`hardware_interfaces_defaults`. It is also possible
to override the defaults for any interfaces by setting one of the options named
``default_<IFACE>_interface``, where ``<IFACE>`` is the interface name.
For example:

.. code-block:: ini

    [DEFAULT]
    default_deploy_interface = direct
    default_network_interface = neutron

This configuration forces the default *deploy* interface to be ``direct`` and
the default *network* interface to be ``neutron`` for all hardware types.

The defaults are calculated and set on a node when creating it or updating
its hardware type. Thus, changing these configuration options has no effect on
existing nodes.

.. warning::
   The default interface implementation must be configured the same way
   across all conductors in the cloud, except maybe for a short period of time
   during an upgrade or configuration update. Otherwise the default
   implementation will depend on which conductor handles which node, and this
   mapping is not predictable or even persistent.

.. warning::
   These options should be used with care. If a hardware type does not
   support the provided default implementation, its users will have to always
   provide an explicit value for this interface when creating a node.

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

See :doc:`/admin/drivers` for the required configuration of each driver.

.. _driver composition reform specification: https://specs.openstack.org/openstack/ironic-specs/specs/approved/driver-composition-reform.html
.. _setup.cfg: https://git.openstack.org/cgit/openstack/ironic/tree/setup.cfg
.. _iSCSI: https://en.wikipedia.org/wiki/ISCSI
.. _ironic-inspector: https://docs.openstack.org/ironic-inspector/pike/
