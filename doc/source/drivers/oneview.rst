.. _oneview:

===============
OneView drivers
===============

Overview
========

HP OneView [1]_ is a single integrated platform, packaged as an appliance that
implements a software-defined approach to managing physical infrastructure.
The appliance supports scenarios such as deploying bare metal servers, for
instance. In this context, the ``HP OneView driver`` for ironic enables the
users of OneView to use ironic as a bare metal provider to their managed
physical hardware.

Currently there are two OneView drivers:

* ``iscsi_pxe_oneview``
* ``agent_pxe_oneview``

The ``iscsi_pxe_oneview`` and ``agent_pxe_oneview`` drivers implement the
core interfaces of an ironic Driver [2]_, and use the ``python-oneviewclient``
[3]_ to provide communication between ironic and OneView through OneView's
REST API.

To provide a bare metal instance there are four components involved in the
process:

* The ironic service
* The ironic driver for OneView, which can be:
    * `iscsi_pxe_oneview` or
    * `agent_pxe_oneview`
* The python-oneviewclient library
* The OneView appliance

The role of ironic is to serve as a bare metal provider to OneView's managed
physical hardware and to provide communication with other necessary OpenStack
services such as Nova and Glance. When ironic receives a boot request, it
works together with the ironic OneView driver to access a machine in OneView,
the ``python-oneviewclient`` being responsible for the communication with the
OneView appliance.

The Mitaka version of the ironic OneView drivers only supported what we call
**pre-allocation** of nodes, meaning that resources in OneView are allocated
prior to the node being made available in ironic. This model is deprecated and
will be supported until OpenStack's Pike release. From the Newton release on,
OneView drivers enables a new feature called **dynamic allocation** of nodes
[6]_. In this model, the driver allocates resources in OneView only at boot
time, allowing idle resources in ironic to be used by OneView users, enabling
actual resource sharing among ironic and OneView users.

Since OneView can claim nodes in ``available`` state at any time, a set of
tasks runs periodically to detect nodes in use by OneView. A node in use by
OneView is placed in ``manageable`` state and has maintenance mode set. Once
the node is no longer in use, these tasks will make place them back in
``available`` state and clear maintenance mode.

Prerequisites
=============

The following requirements apply for both ``iscsi_pxe_oneview`` and
``agent_pxe_oneview`` drivers:

* ``OneView appliance`` is the HP physical infrastructure manager to be
  integrated with the OneView drivers.

  Minimum version supported is 2.0.

* ``python-oneviewclient`` is a python package containing a client to manage
  the communication between ironic and OneView.

  Install the ``python-oneviewclient`` module to enable the communication.
  Minimum version required is 2.4.0 but it is recommended to install the most
  up-to-date version.::

  $ pip install "python-oneviewclient<3.0.0,>=2.4.0"

Tested platforms
================

* The OneView appliance used for testing was the OneView 2.0.

* The Enclosure used for testing was the ``BladeSystem c7000 Enclosure G2``.

* The drivers should work on HP Proliant Gen8 and Gen9 Servers supported by
  OneView 2.0 and above, or any hardware whose network can be managed by
  OneView's ServerProfile. It has been tested with the following servers:

  - Proliant BL460c Gen8
  - Proliant BL460c Gen9
  - Proliant BL465c Gen8
  - Proliant DL360 Gen9 (starting with python-oneviewclient 2.1.0)

  Notice that for the driver to work correctly with Gen8 and Gen9 DL servers
  in general, the hardware also needs to run version 4.2.3 of iLO, with
  Redfish enabled.

Drivers
=======

iscsi_pxe_oneview driver
^^^^^^^^^^^^^^^^^^^^^^^^

Overview
~~~~~~~~

``iscsi_pxe_oneview`` driver uses PXEBoot for boot and ISCSIDeploy for deploy.

Configuring and enabling the driver
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

1. Add ``iscsi_pxe_oneview`` to the list of ``enabled_drivers`` in your
   ``ironic.conf`` file. For example::

    enabled_drivers = iscsi_pxe_oneview

2. Update the [oneview] section of your ``ironic.conf`` file with your
   OneView credentials and CA certificate files information.

.. note::
   If you are using the deprecated ``pre-allocation`` feature (i.e.:
   ``dynamic_allocation`` is set to False on all nodes), you can disable the
   driver periodic tasks by setting ``enable_periodic_tasks=false`` on the
   [oneview] section of ``ironic.conf``

.. note::
   An operator can set the ``periodic_check_interval`` option in the [oneview]
   section to set the interval between running the periodic check. The default
   value is 300 seconds (5 minutes). A lower value will reduce the likelyhood
   of races between ironic and OneView at the cost of being more resource
   intensive.

3. Restart the ironic conductor service. For Ubuntu users, do::

    $ sudo service ironic-conductor restart

See [5]_ for more information.

Deploy process
~~~~~~~~~~~~~~

Here is an overview of the deploy process for this driver:

1. Admin configures the Proliant baremetal node to use ``iscsi_pxe_oneview``
   driver.
2. ironic gets a request to deploy a Glance image on the baremetal node.
3. Driver sets the boot device to PXE.
4. Driver powers on the baremetal node.
5. ironic downloads the deploy and user images from a TFTP server.
6. Driver reboots the baremetal node.
7. User image is now deployed.
8. Driver powers off the machine.
9. Driver sets boot device to Disk.
10. Driver powers on the machine.
11. Baremetal node is active and ready to be used.

agent_pxe_oneview driver
^^^^^^^^^^^^^^^^^^^^^^^^

Overview
~~~~~~~~

``agent_pxe_oneview`` driver uses PXEBoot for boot and AgentDeploy for deploy.

Configuring and enabling the driver
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

1. Add ``agent_pxe_oneview`` to the list of ``enabled_drivers`` in your
   ``ironic.conf``. For example::

    enabled_drivers = fake,pxe_ssh,pxe_ipmitool,agent_pxe_oneview

2. Update the [oneview] section of your ``ironic.conf`` file with your
   OneView credentials and CA certificate files information.

.. note::
   If you are using the deprecated ``pre-allocation`` feature (i.e.:
   ``dynamic_allocation`` is set to False on all nodes), you can disable the
   driver periodic tasks by setting ``enable_periodic_tasks=false`` on the
   [oneview] section of ``ironic.conf``

.. note::
   An operator can set the ``periodic_check_interval`` option in the [oneview]
   section to set the interval between running the periodic check. The default
   value is 300 seconds (5 minutes). A lower value will reduce the likelyhood
   of races between ironic and OneView at the cost of being more resource
   intensive.

3. Restart the ironic conductor service. For Ubuntu users, do::

    $ service ironic-conductor restart

See [5]_ for more information.

Deploy process
~~~~~~~~~~~~~~

Here is an overview of the deploy process for this driver:

1. Admin configures the Proliant baremetal node to use ``agent_pxe_oneview``
   driver.
2. ironic gets a request to deploy a Glance image on the baremetal node.
3. Driver sets the boot device to PXE.
4. Driver powers on the baremetal node.
5. Node downloads the agent deploy images.
6. Agent downloads the user images and writes it to disk.
7. Driver reboots the baremetal node.
8. User image is now deployed.
9. Driver powers off the machine.
10. Driver sets boot device to Disk.
11. Driver powers on the machine.
12. Baremetal node is active and ready to be used.

Registering a OneView node in ironic
====================================

Nodes configured to use any of the OneView drivers should have the ``driver``
property set to ``iscsi_pxe_oneview`` or ``agent_pxe_oneview``. Considering
our context, a node is the representation of a ``Server Hardware`` in OneView,
and should be consistent with all its properties and related components, such
as ``Server Hardware Type``, ``Server Profile Template``, ``Enclosure Group``,
etc. In this case, to be enrolled, the node must have the following parameters:

* In ``driver_info``

  - ``server_hardware_uri``: URI of the ``Server Hardware`` on OneView.

  - ``dynamic_allocation``: Boolean value to enable or disable (True/False)
    ``dynamic allocation`` for the given node. If this parameter is not set,
    the driver will consider the ``pre-allocation`` model to maintain
    compatibility on ironic upgrade. The support for this key will be dropped
    in the Pike release, where only dynamic allocation will be used.

* In ``properties/capabilities``

  - ``server_hardware_type_uri``: URI of the ``Server Hardware Type`` of the
    ``Server Hardware``.
  - ``server_profile_template_uri``: URI of the ``Server Profile Template`` used
    to create the ``Server Profile`` of the ``Server Hardware``.
  - ``enclosure_group_uri`` (optional): URI of the ``Enclosure Group`` of the
    ``Server Hardware``.

To enroll a node with any of the OneView drivers, do::

  $ ironic node-create -d $DRIVER_NAME

To update the ``driver_info`` field of a newly enrolled OneView node, do::

  $ ironic node-update $NODE_UUID add \
    driver_info/server_hardware_uri=$SH_URI

To update the ``properties/capabilities`` namespace of a newly enrolled
OneView node, do::

  $ ironic node-update $NODE_UUID add \
    properties/capabilities=server_hardware_type_uri:$SHT_URI,enclosure_group_uri:$EG_URI,server_profile_template_uri=$SPT_URI

In order to deploy, ironic will create and apply, at boot time, a ``Server
Profile`` based on the ``Server Profile Template`` specified on the node to the
``Server Hardware`` it represents on OneView. The URI of such ``Server Profile``
will be stored in ``driver_info.applied_server_profile_uri`` field while the
Server is allocated to ironic.

The ``Server Profile Templates`` and, therefore, the ``Server Profiles`` derived
from them MUST comply with the following requirements:

* The option `MAC Address` in the `Advanced` section of
  ``Server Profile``/``Server Profile Template`` should be set to `Physical`
  option;

* Their first `Connection` interface should be:

  * Connected to ironic's provisioning network and;
  * The `Boot` option should be set to primary.

Node ports should be created considering the **MAC address of the first
Interface** of the given ``Server Hardware``.

.. note::
   Old versions of ironic using ``pre-allocation`` model (before Newton
   release) and nodes with `dynamic_allocation` flag disabled shall have their
   ``Server Profiles`` applied during node enrollment and can have their ports
   created using the `Virtual` MAC addresses provided on ``Server Profile``
   application.

To tell ironic which NIC should be connected to the provisioning network, do::

  $ ironic port-create -n $NODE_UUID -a $MAC_ADDRESS

For more information on the enrollment process of an ironic node, see [4]_.

For more information on the definitions of ``Server Hardware``, ``Server
Profile``, ``Server Profile Template`` and other OneView entities, refer to
[1]_ or browse Help in your OneView appliance menu.

Migrating from pre-allocation to dynamic allocation
===================================================

The migration of a node from an ironic deployment using ``pre-allocation``
model to the new ``dynamic allocation`` model can be done by using
``ironic-oneview-cli`` facilities to migrate nodes (further details on [8]_).
However, the same results can be achieved using the ironic CLI as explained
below.

Checking if a node can be migrated
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

It is recommended to migrate nodes which are in a stable `provision state`. That
means the the conductor is not performing an operation with the node, what can
impact in the execution of a migration. The possible stable `provision_state`
values [9_] are: `enroll`, `manageable`, `available`, `active`, `error`,
`clean failed` and `inspect failed`.

Dynamic allocation mode changes the way a ``Server Profile`` is associated with
a node. In ``pre-allocation`` mode, when a node is registered in ironic, there
must be a ``Server Profile`` applied to the ``Server Hardware`` represented by
the given node what means, from the OneView point of view, the hardware is in
use. In the ``dynamic allocation`` mode a ``Server Hardware`` is associated only
when the node is in use by the Compute service or the OneView itself. As a
result, there are different steps to perform if the node has an instance
provisioned, in other words, when the `provisioning_state` is set to `active`.

.. note::
   Verify if the node has not already been migrated checking if there is
   a `dynamic_allocation` field set to ``True`` in the `driver_info` namespace
   doing::

     $ ironic node-show  --fields driver_info

Migrating nodes in `active` state
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

List nodes that are in `active` state doing::

  $ ironic node-list --provision-state active --fields uuid driver_info

Execute the following steps for each node:

1. Remove the node's ``Server Profile`` from the ``Server Hardware`` in OneView.
   To identify which ``Server Profile`` is associated with a node check the
   property ``server_hardware_uri`` in the ``driver_info`` namespace doing::

   $ ironic node-show <node-uuid> --fields driver_info

2. Then, using the ``server_hardware_uri``, log into OneView and remove the
   ``Server Profile``.

3. Finally, set the `dynamic_allocation` flag in the ``driver_info`` namespace
   to ``True`` in order to finish the migration of the node doing::

   $ ironic node-update <node-uuid> add driver_info/dynamic_allocation=True

Other cases for migration
^^^^^^^^^^^^^^^^^^^^^^^^^

Remember these steps are valid for nodes in the following states: `enroll`,
`manageable`, `available`, `error`, `clean failed` and `inspect failed`. So,
list the nodes in a given state, then execute the migration following steps for
each node:

1. Place the node in maintenance mode to prevent ironic from working on the node
   during the migration doing::

   $ ironic node-set-maintenance --reason "Migrating node to dynamic allocation" <node_uuid> true

   .. note::
      It's recommended to check if the node's state has not changed as there is no way
      of locking the node between these commands.

2. Identify which ``Server Profile`` is associated by checking the property
   ``server_hardware_uri`` in the ``driver_info`` namespace. Using the
   ``server_hardware_uri``, log into OneView and remove the ``Server Profile``.

3. Set the `dynamic_allocation` to ``True`` in the flag ``driver_info``
   namespace doing::

   $ ironic node-update $NODE_UUID add driver_info/dynamic_allocation=True

4. Finally, in order to put the node back into the resource pool, remove the
   node from maintenance mode doing::

   $ ironic node-set-maintenance <node_uuid> false

3rd Party Tools
===============

In order to ease user manual tasks, which are often time-consuming, we provide
useful tools that work nicely with the OneView drivers.

ironic-oneview-cli
^^^^^^^^^^^^^^^^^^

The ``ironic-oneView`` CLI is a command line interface for management tasks
involving OneView nodes. Its features include a facility to create of ironic
nodes with all required parameters for OneView nodes, creation of Nova flavors
for OneView nodes and, starting from version 0.3.0, the migration of nodes from
``pre-allocation`` to the ``dynamic allocation`` model.

For more details on how Ironic-OneView CLI works and how to set it up, see
[8]_.

ironic-oneviewd
^^^^^^^^^^^^^^^

The ``ironic-oneviewd`` daemon monitors the ironic inventory of resources and
providing facilities to operators managing OneView driver deployments. The
daemon supports both allocation models (dynamic and pre-allocation) as of
version 0.1.0.

For more details on how Ironic-OneViewd works and how to set it up, see [7]_.

References
==========
.. [1] HP OneView - https://www.hpe.com/us/en/integrated-systems/software.html
.. [2] Driver interfaces - http://docs.openstack.org/developer/ironic/dev/architecture.html#drivers
.. [3] python-oneviewclient - https://pypi.python.org/pypi/python-oneviewclient
.. [4] Enrollment process of a node - http://docs.openstack.org/project-install-guide/baremetal/newton/enrollment.html
.. [5] ironic install guide - http://docs.openstack.org/project-install-guide/baremetal/newton/
.. [6] Dynamic Allocation in OneView drivers - http://specs.openstack.org/openstack/ironic-specs/specs/not-implemented/oneview-drivers-dynamic-allocation.html
.. [7] ironic-oneviewd - https://pypi.python.org/pypi/ironic-oneviewd/
.. [8] ironic-oneview-cli - https://pypi.python.org/pypi/ironic-oneview-cli/
.. [9] Ironic’s State Machine - http://docs.openstack.org/developer/ironic/dev/states.html#states
