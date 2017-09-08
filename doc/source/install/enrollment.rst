.. _enrollment:

Enrollment
==========

After all the services have been properly configured, you should enroll your
hardware with the Bare Metal service, and confirm that the Compute service sees
the available hardware. The nodes will be visible to the Compute service once
they are in the ``available`` provision state.

.. note::
   After enrolling nodes with the Bare Metal service, the Compute service
   will not be immediately notified of the new resources. The Compute service's
   resource tracker syncs periodically, and so any changes made directly to the
   Bare Metal service's resources will become visible in the Compute service
   only after the next run of that periodic task.
   More information is in the :ref:`troubleshooting-install` section.

.. note::
   Any bare metal node that is visible to the Compute service may have a
   workload scheduled to it, if both the ``power`` and ``deploy`` interfaces
   pass the ``validate`` check.
   If you wish to exclude a node from the Compute service's scheduler, for
   instance so that you can perform maintenance on it, you can set the node to
   "maintenance" mode.
   For more information see the :ref:`maintenance_mode` section.

Choosing a driver
-----------------

When enrolling a node, the most important information to supply is *driver*.
This can be either a *classic driver* or a *hardware type* - see
:doc:`enabling-drivers` for the difference. The ``driver-list`` command can
be used to list all drivers (of both types) enabled on all hosts:

.. code-block:: console

    ironic driver-list
    +---------------------+-----------------------+
    | Supported driver(s) | Active host(s)        |
    +---------------------+-----------------------+
    | ipmi                | localhost.localdomain |
    | pxe_ipmitool        | localhost.localdomain |
    +---------------------+-----------------------+

Starting with API version 1.31 (and ``python-ironicclient`` 1.13), you can
also list only classic or only dynamic drivers:

.. code-block:: console

    ironic --ironic-api-version 1.31 driver-list -t dynamic
    +---------------------+-----------------------+
    | Supported driver(s) | Active host(s)        |
    +---------------------+-----------------------+
    | ipmi                | localhost.localdomain |
    +---------------------+-----------------------+

The specific driver to use should be picked based on actual hardware
capabilities and expected features. See :doc:`/admin/drivers` for more hints
on that.

Each driver has a list of *driver properties* that need to be specified via
the node's ``driver_info`` field, in order for the driver to operate on node.
This list consists of the properties of the hardware interfaces that the driver
uses. These driver properties are available with the ``driver-properties``
command:

.. code-block:: console

    $ ironic driver-properties pxe_ipmitool
    +----------------------+-------------------------------------------------------------------------------------------------------------+
    | Property             | Description                                                                                                 |
    +----------------------+-------------------------------------------------------------------------------------------------------------+
    | ipmi_address         | IP address or hostname of the node. Required.                                                               |
    | ipmi_password        | password. Optional.                                                                                         |
    | ipmi_username        | username; default is NULL user. Optional.                                                                   |
    | ...                  | ...                                                                                                         |
    | deploy_kernel        | UUID (from Glance) of the deployment kernel. Required.                                                      |
    | deploy_ramdisk       | UUID (from Glance) of the ramdisk that is mounted at boot time. Required.                                   |
    +----------------------+-------------------------------------------------------------------------------------------------------------+

The properties marked as required must be supplied either during node creation
or shortly after. Some properties may only be required for certain features.

Note on API versions
--------------------

Starting with API version 1.11, the Bare Metal service added a new initial
provision state of ``enroll`` to its state machine. When this or later API
version is used, new nodes get this state instead of ``available``.

Existing automation tooling that use an API version lower than 1.11 are not
affected, since the initial provision state is still ``available``.
However, using API version 1.11 or above may break existing automation tooling
with respect to node creation.

The default API version used by (the most recent) python-ironicclient is 1.9,
but it may change in the future and should not be relied on.

In the examples below we will use version 1.11 of the Bare metal API.
This gives us the following advantages:

* Explicit power credentials validation before leaving the ``enroll`` state.
* Running node cleaning before entering the ``available`` state.
* Not exposing half-configured nodes to the scheduler.

To set the API version for all commands, you can set the environment variable
``IRONIC_API_VERSION``. For the OpenStackClient baremetal plugin, set
the ``OS_BAREMETAL_API_VERSION`` variable to the same value. For example:

.. code-block:: console

    $ export IRONIC_API_VERSION=1.11
    $ export OS_BAREMETAL_API_VERSION=1.11

Enrollment process
------------------

Creating a node
~~~~~~~~~~~~~~~

This section describes the main steps to enroll a node and make it available
for provisioning. Some steps are shown separately for illustration purposes,
and may be combined if desired.

#. Create a node in the Bare Metal service with the ``node-create`` command.
   At a minimum, you must specify the driver name (for example,
   ``pxe_ipmitool``, ``agent_ipmitool`` or ``ipmi``).

   This command returns the node UUID along with other information
   about the node. The node's provision state will be ``enroll``:

   .. code-block:: console

    $ export IRONIC_API_VERSION=1.11
    $ ironic node-create -d pxe_ipmitool
    +--------------+--------------------------------------+
    | Property     | Value                                |
    +--------------+--------------------------------------+
    | uuid         | dfc6189f-ad83-4261-9bda-b27258eb1987 |
    | driver_info  | {}                                   |
    | extra        | {}                                   |
    | driver       | pxe_ipmitool                         |
    | chassis_uuid |                                      |
    | properties   | {}                                   |
    | name         | None                                 |
    +--------------+--------------------------------------+

    $ ironic node-show dfc6189f-ad83-4261-9bda-b27258eb1987
    +------------------------+--------------------------------------+
    | Property               | Value                                |
    +------------------------+--------------------------------------+
    | target_power_state     | None                                 |
    | extra                  | {}                                   |
    | last_error             | None                                 |
    | maintenance_reason     | None                                 |
    | provision_state        | enroll                               |
    | uuid                   | dfc6189f-ad83-4261-9bda-b27258eb1987 |
    | console_enabled        | False                                |
    | target_provision_state | None                                 |
    | provision_updated_at   | None                                 |
    | maintenance            | False                                |
    | power_state            | None                                 |
    | driver                 | pxe_ipmitool                         |
    | properties             | {}                                   |
    | instance_uuid          | None                                 |
    | name                   | None                                 |
    | driver_info            | {}                                   |
    | ...                    | ...                                  |
    +------------------------+--------------------------------------+

   A node may also be referred to by a logical name as well as its UUID.
   A name can be assigned to the node during its creation by adding the ``-n``
   option to the ``node-create`` command or by updating an existing node with
   the ``node-update`` command. See `Logical Names`_ for examples.

#. Starting with API version 1.31 (and ``python-ironicclient`` 1.13), you can
   pick which hardware interface to use with nodes that use hardware types.
   Each interface is represented by a node field called ``<IFACE>_interface``
   where ``<IFACE>`` in the interface type, e.g. ``boot``. See
   :doc:`enabling-drivers` for details on hardware interfaces and
   :doc:`/admin/upgrade-to-hardware-types` for the matching between classic
   drivers and hardware types.

   An interface can be set either separately:

   .. code-block:: console

    $ ironic --ironic-api-version 1.31 node-update $NODE_UUID replace \
        deploy_interface=direct \
        raid_interface=agent

   or set during node creation:

   .. code-block:: console

    $ ironic --ironic-api-version 1.31 node-create -d ipmi \
        --deploy-interface direct \
        --raid-interface agent

   If no value is provided for some interfaces, `Defaults for hardware
   interfaces`_ are used instead.

   It's an error to try changing this field for a node with a *classic driver*,
   and setting node's driver to classic one causes these fields to be set
   to ``None`` automatically.

#. Update the node ``driver_info`` with the required driver properties, so that
   the Bare Metal service can manage the node:

   .. code-block:: console

    $ ironic node-update $NODE_UUID add \
        driver_info/ipmi_username=$USER \
        driver_info/ipmi_password=$PASS \
        driver_info/ipmi_address=$ADDRESS

   .. note::
      If IPMI is running on a port other than 623 (the default). The port must
      be added to ``driver_info`` by specifying the ``ipmi_port`` value.
      Example:

      .. code-block:: console

       $ ironic node-update $NODE_UUID add driver_info/ipmi_port=$PORT_NUMBER

   You may also specify all ``driver_info`` parameters during node
   creation by passing the **-i** option multiple times:

   .. code-block:: console

     $ ironic node-create -d pxe_ipmitool \
         -i ipmi_username=$USER \
         -i ipmi_password=$PASS \
         -i ipmi_address=$ADDRESS

   See `Choosing a driver`_ above for details on driver properties.

#. Specify a deploy kernel and ramdisk compatible with the node's driver,
   for example:

   .. code-block:: console

    $ ironic node-update $NODE_UUID add \
        driver_info/deploy_kernel=$DEPLOY_VMLINUZ_UUID \
        driver_info/deploy_ramdisk=$DEPLOY_INITRD_UUID

   See :doc:`configure-glance-images` for details.

#. You must also inform the Bare Metal service of the network interface cards
   which are part of the node by creating a port with each NIC's MAC address.
   These MAC addresses are passed to the Networking service during instance
   provisioning and used to configure the network appropriately:

   .. code-block:: console

    $ ironic port-create -n $NODE_UUID -a $MAC_ADDRESS

.. _enrollment-scheduling:

Adding scheduling information
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

#. Assign a *resource class* to the node. A *resource class* should represent
   a class of hardware in your data center, that corresponds to a Compute
   flavor.

   For example, let's split hardware into these three groups:

   #. nodes with a lot of RAM and powerful CPU for computational tasks,
   #. nodes with powerful GPU for OpenCL computing,
   #. smaller nodes for development and testing.

   We can define three resource classes to reflect these hardware groups, named
   ``large-cpu``, ``large-gpu`` and ``small`` respectively. Then, for each node
   in each of the hardware groups, we'll set their ``resource_class``
   appropriately via:

   .. code-block:: console

    $ openstack --os-baremetal-api-version 1.21 baremetal node set $NODE_UUID \
        --resource-class $CLASS_NAME

   The ``--resource-class`` argument can also be used when creating a node:

   .. code-block:: console

    $ openstack --os-baremetal-api-version 1.21 baremetal node create \
        --driver $DRIVER --resource-class $CLASS_NAME

   To use resource classes for scheduling you need to update your flavors as
   described in :doc:`configure-nova-flavors`.

   .. warning::
      Scheduling based on resource classes will replace scheduling based on
      properties in the Queens release.

   .. note::
      This is not required for standalone deployments, only for those using
      the Compute service for provisioning bare metal instances.

#. Update the node's properties to match the actual hardware of the node:

   .. code-block:: console

    $ ironic node-update $NODE_UUID add \
        properties/cpus=$CPU_COUNT \
        properties/memory_mb=$RAM_MB \
        properties/local_gb=$DISK_GB \
        properties/cpu_arch=$ARCH

   As above, these can also be specified at node creation by passing the **-p**
   option to ``node-create`` multiple times:

   .. code-block:: console

     $ ironic node-create -d pxe_ipmitool \
         -i ipmi_username=$USER \
         -i ipmi_password=$PASS \
         -i ipmi_address=$ADDRESS \
         -p cpus=$CPU_COUNT \
         -p memory_mb=$RAM_MB \
         -p local_gb=$DISK_GB \
         -p cpu_arch=$ARCH

   These values can also be discovered during `Hardware Inspection`_.

   .. warning::
      If scheduling based on resource classes is not used, the three properties
      ``cpus``, ``memory_mb`` and ``local_gb`` must match ones defined on the
      flavor created when :doc:`configure-nova-flavors`.

   .. warning::
      The value provided for the ``local_gb`` property must match the size of
      the root device you're going to deploy on. By default
      **ironic-python-agent** picks the smallest disk which is not smaller
      than 4 GiB.

      If you override this logic by using root device hints (see
      :ref:`root-device-hints`), the ``local_gb`` value should match the size
      of picked target disk.

#. If you wish to perform more advanced scheduling of the instances based on
   hardware capabilities, you may add metadata to each node that will be
   exposed to the the Compute scheduler (see: `ComputeCapabilitiesFilter`_).
   A full explanation of this is outside of the scope of this document. It can
   be done through the special ``capabilities`` member of node properties:

   .. code-block:: console

    $ ironic node-update $NODE_UUID add \
        properties/capabilities=key1:val1,key2:val2

   Some capabilities can also be discovered during `Hardware Inspection`_.

Validating node information
~~~~~~~~~~~~~~~~~~~~~~~~~~~

#. To check if Bare Metal service has the minimum information necessary for
   a node's driver to be functional, you may ``validate`` it:

   .. code-block:: console

    $ ironic node-validate $NODE_UUID
    +------------+--------+--------+
    | Interface  | Result | Reason |
    +------------+--------+--------+
    | console    | True   |        |
    | deploy     | True   |        |
    | management | True   |        |
    | power      | True   |        |
    +------------+--------+--------+

   If the node fails validation, each driver interface will return information
   as to why it failed:

   .. code-block:: console

    $ ironic node-validate $NODE_UUID
    +------------+--------+-------------------------------------------------------------------------------------------------------------------------------------+
    | Interface  | Result | Reason                                                                                                                              |
    +------------+--------+-------------------------------------------------------------------------------------------------------------------------------------+
    | console    | None   | not supported                                                                                                                       |
    | deploy     | False  | Cannot validate iSCSI deploy. Some parameters were missing in node's instance_info. Missing are: ['root_gb', 'image_source']        |
    | management | False  | Missing the following IPMI credentials in node's driver_info: ['ipmi_address'].                                                     |
    | power      | False  | Missing the following IPMI credentials in node's driver_info: ['ipmi_address'].                                                     |
    +------------+--------+-------------------------------------------------------------------------------------------------------------------------------------+

   When using the Compute Service with the Bare Metal service, it is safe to
   ignore the deploy interface's validation error due to lack of image
   information. You may continue the enrollment process. This information will
   be set by the Compute Service just before deploying, when an instance is
   requested:

   .. code-block:: console

    $ ironic node-validate $NODE_UUID
    +------------+--------+------------------------------------------------------------------------------------------------------------------------------------------------------------------+
    | Interface  | Result | Reason                                                                                                                                                           |
    +------------+--------+------------------------------------------------------------------------------------------------------------------------------------------------------------------+
    | console    | True   |                                                                                                                                                                  |
    | deploy     | False  | Cannot validate image information for node because one or more parameters are missing from its instance_info. Missing are: ['ramdisk', 'kernel', 'image_source'] |
    | management | True   |                                                                                                                                                                  |
    | power      | True   |                                                                                                                                                                  |
    +------------+--------+------------------------------------------------------------------------------------------------------------------------------------------------------------------+

Making node available for deployment
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

In order for nodes to be available for deploying workloads on them, nodes
must be in the ``available`` provision state. To do this, nodes
created with API version 1.11 and above must be moved from the ``enroll`` state
to the ``manageable`` state and then to the ``available`` state.
This section can be safely skipped, if API version 1.10 or earlier is used
(which is the case by default).

After creating a node and before moving it from its initial provision state of
``enroll``, basic power and port information needs to be configured on the node.
The Bare Metal service needs this information because it verifies that it is
capable of controlling the node when transitioning the node from ``enroll`` to
``manageable`` state.

To move a node from ``enroll`` to ``manageable`` provision state:

.. code-block:: console

    $ ironic --ironic-api-version 1.11 node-set-provision-state $NODE_UUID manage
    $ ironic node-show $NODE_UUID
    +------------------------+--------------------------------------------------------------------+
    | Property               | Value                                                              |
    +------------------------+--------------------------------------------------------------------+
    | ...                    | ...                                                                |
    | provision_state        | manageable                                                         | <- verify correct state
    | uuid                   | 0eb013bb-1e4b-4f4c-94b5-2e7468242611                               |
    | ...                    | ...                                                                |
    +------------------------+--------------------------------------------------------------------+

.. note:: Since it is an asynchronous call, the response for
          ``ironic node-set-provision-state`` will not indicate whether the
          transition succeeded or not. You can check the status of the
          operation via ``ironic node-show``. If it was successful,
          ``provision_state`` will be in the desired state. If it failed,
          there will be information in the node's ``last_error``.

When a node is moved from the ``manageable`` to ``available`` provision
state, the node will go through automated cleaning if configured to do so (see
:ref:`configure-cleaning`).

To move a node from ``manageable`` to ``available`` provision state:

.. code-block:: console

    $ ironic --ironic-api-version 1.11 node-set-provision-state $NODE_UUID provide
    $ ironic node-show $NODE_UUID
    +------------------------+--------------------------------------------------------------------+
    | Property               | Value                                                              |
    +------------------------+--------------------------------------------------------------------+
    | ...                    | ...                                                                |
    | provision_state        | available                                                          | < - verify correct state
    | uuid                   | 0eb013bb-1e4b-4f4c-94b5-2e7468242611                               |
    | ...                    | ...                                                                |
    +------------------------+--------------------------------------------------------------------+

For more details on the Bare Metal service's state machine, see the
:doc:`/contributor/states` documentation.

.. _ComputeCapabilitiesFilter: https://docs.openstack.org/nova/pike/user/filter-scheduler.html

Mapping nodes to Compute cells
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

If the Compute service is used for scheduling, and the
``discover_hosts_in_cells_interval`` was not set as described in
:doc:`configure-compute`, then log into any controller node and run the
following command to map the new node(s) to Compute cells::

    nova-manage cell_v2 discover_hosts

Logical names
-------------

A node may also be referred to by a logical name as well as its UUID.
Names can be assigned either during its creation by adding the ``-n``
option to the ``node-create`` command or by updating an existing node with
the ``node-update`` command.

Node names must be unique, and conform to:

- rfc952_
- rfc1123_
- wiki_hostname_

The node is named 'example' in the following examples:

.. code-block:: console

    $ ironic node-create -d agent_ipmitool -n example

or

.. code-block:: console

    $ ironic node-update $NODE_UUID add name=example


Once assigned a logical name, a node can then be referred to by name or
UUID interchangeably:

.. code-block:: console

    $ ironic node-create -d agent_ipmitool -n example
    +--------------+--------------------------------------+
    | Property     | Value                                |
    +--------------+--------------------------------------+
    | uuid         | 71e01002-8662-434d-aafd-f068f69bb85e |
    | driver_info  | {}                                   |
    | extra        | {}                                   |
    | driver       | agent_ipmitool                       |
    | chassis_uuid |                                      |
    | properties   | {}                                   |
    | name         | example                              |
    +--------------+--------------------------------------+

    $ ironic node-show example
    +------------------------+--------------------------------------+
    | Property               | Value                                |
    +------------------------+--------------------------------------+
    | target_power_state     | None                                 |
    | extra                  | {}                                   |
    | last_error             | None                                 |
    | updated_at             | 2015-04-24T16:23:46+00:00            |
    | ...                    | ...                                  |
    | instance_info          | {}                                   |
    +------------------------+--------------------------------------+

.. _rfc952: http://tools.ietf.org/html/rfc952
.. _rfc1123: http://tools.ietf.org/html/rfc1123
.. _wiki_hostname: http://en.wikipedia.org/wiki/Hostname

.. _hardware_interfaces_defaults:

Defaults for hardware interfaces
--------------------------------

For *classic drivers* all hardware interface implementations (except for the
*network interface*) are hardcoded and cannot be changed.
For *hardware types*, users can request one of enabled implementations when
creating or updating a node as explained in `Creating a node`_.

When no value is provided for a certain interface when creating a node, or
changing a node's hardware type, the default value is used. You can use
the driver details command to list the current enabled and default
interfaces for a hardware type (for your deployment):

.. code-block:: console

    $ openstack --os-baremetal-api-version 1.31 baremetal driver show ipmi
    +-------------------------------+----------------+
    | Field                         | Value          |
    +-------------------------------+----------------+
    | default_boot_interface        | pxe            |
    | default_console_interface     | no-console     |
    | default_deploy_interface      | iscsi          |
    | default_inspect_interface     | no-inspect     |
    | default_management_interface  | ipmitool       |
    | default_network_interface     | flat           |
    | default_power_interface       | ipmitool       |
    | default_raid_interface        | no-raid        |
    | default_vendor_interface      | no-vendor      |
    | enabled_boot_interfaces       | pxe            |
    | enabled_console_interfaces    | no-console     |
    | enabled_deploy_interfaces     | iscsi, direct  |
    | enabled_inspect_interfaces    | no-inspect     |
    | enabled_management_interfaces | ipmitool       |
    | enabled_network_interfaces    | flat, noop     |
    | enabled_power_interfaces      | ipmitool       |
    | enabled_raid_interfaces       | no-raid, agent |
    | enabled_vendor_interfaces     | no-vendor      |
    | hosts                         | ironic-host-1  |
    | name                          | ipmi           |
    | type                          | dynamic        |
    +-------------------------------+----------------+

The defaults are calculated as follows:

#. If the ``default_<IFACE>_interface`` configuration option (where
   ``<IFACE>`` is the interface name) is set, its value is used as the default.

   If this implementation is not compatible with the node's hardware type,
   an error is returned to a user. An explicit value has to be provided
   for the node's ``<IFACE>_interface`` field in this case.

#. Otherwise, the first supported implementation that is enabled by an
   operator is used as the default.

   A list of supported implementations is calculated by taking the intersection
   between the implementations supported by the node's hardware type and
   implementations enabled by the ``enabled_<IFACE>_interfaces`` option (where
   ``<IFACE>`` is the interface name). The calculation preserves the order
   of items, as provided by the hardware type.

   If the list of supported implementations is not empty, the first one is
   used.  Otherwise, an error is returned to a user. In this case, an explicit
   value has to be provided for the ``<IFACE>_interface`` field.

See :doc:`enabling-drivers` for more details on configuration.

Example
~~~~~~~

Consider the following configuration (shortened for simplicity):

.. code-block:: ini

    [DEFAULT]
    enabled_hardware_types = ipmi,redfish
    enabled_console_interfaces = no-console,ipmitool-shellinabox
    enabled_deploy_interfaces = iscsi,direct
    enabled_management_interfaces = ipmitool,redfish
    enabled_power_interfaces = ipmitool,redfish
    default_deploy_interface = direct

A new node is created with the ``ipmi`` driver and no interfaces specified:

.. code-block:: console

    $ export IRONIC_API_VERSION=1.31
    $ ironic node-create -d ipmi
    +--------------+--------------------------------------+
    | Property     | Value                                |
    +--------------+--------------------------------------+
    | uuid         | dfc6189f-ad83-4261-9bda-b27258eb1987 |
    | driver_info  | {}                                   |
    | extra        | {}                                   |
    | driver       | ipmi                                 |
    | chassis_uuid |                                      |
    | properties   | {}                                   |
    | name         | None                                 |
    +--------------+--------------------------------------+

Then the defaults for the interfaces that will be used by the node in this
example are calculated as follows:

deploy
    An explicit value of ``direct`` is provided for
    ``default_deploy_interface``, so it is used.
power
    No default is configured. The ``ipmi`` hardware type supports only
    ``ipmitool`` power. The intersection between supported power
    interfaces and values provided in the ``enabled_power_interfaces``
    option has only one item: ``ipmitool``. It is used.
console
    No default is configured. The ``ipmi`` hardware type supports the following
    console interfaces: ``ipmitool-socat``, ``ipmitool-shellinabox`` and
    ``no-console`` (in this order). Of these three, only two are enabled:
    ``no-console`` and ``ipmitool-shellinabox`` (order does not matter). The
    intersection contains ``ipmitool-shellinabox`` and ``no-console``.
    The first item is used, and it is ``ipmitool-shellinabox``.
management
    Following the same calculation as *power*, the ``ipmitool`` management
    interface is used.

Hardware Inspection
-------------------

The Bare Metal service supports hardware inspection that simplifies enrolling
nodes - please see :doc:`/admin/inspection` for details.

Tenant Networks and Port Groups
-------------------------------

See :doc:`/admin/multitenancy` and :doc:`/admin/portgroups`.
