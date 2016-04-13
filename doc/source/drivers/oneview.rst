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
will be supported until OpenStack's `P` release. From the Newton release on,
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

  - ``server_hardware_uri``: URI of the Server Hardware on OneView.

  - ``dynamic_allocation``: Boolean value to enable or disable (True/False)
    ``dynamic allocation`` for the given node. If this parameter is not set,
    the driver will consider the ``pre-allocation`` model to maintain
    compatibility on ironic upgrade. The support for this key will be dropped
    in P, where only dynamic allocation will be used.

* In ``properties/capabilities``

  - ``server_hardware_type_uri``: URI of the Server Hardware Type of the
    Server Hardware.
  - ``server_profile_template_uri``: URI of the Server Profile Template used
    to create the Server Profile of the Server Hardware.
  - ``enclosure_group_uri`` (optional): URI of the Enclosure Group of the
    Server Hardware.

To enroll a node with any of the OneView drivers, do::

  $ ironic node-create -d $DRIVER_NAME

To update the ``driver_info`` field of a newly enrolled OneView node, do::

  $ ironic node-update $NODE_UUID add \
    driver_info/server_hardware_uri=$SH_URI

To update the ``properties/capabilities`` namespace of a newly enrolled
OneView node, do::

  $ ironic node-update $NODE_UUID add \
    properties/capabilities=server_hardware_type_uri:$SHT_URI,enclosure_group_uri:$EG_URI,server_profile_template_uri=$SPT_URI

In order to deploy, ironic will create and apply, at boot time, a Server
Profile based on the Server Profile Template specified on the node to the
Server Hardware it represents on OneView. The URI of such Server Profile will
be stored in ``driver_info.applied_server_profile_uri`` field while the Server
is allocated to ironic.

The Server Profile Templates and, therefore, the Server Profiles derived from
them MUST comply with the following requirements:

* The option `MAC Address` in the `Advanced` section of Server Profile/Server
  Profile Template should be set to `Physical` option;
* Their first `Connection` interface should be:

    * Connected to ironic's provisioning network and;
    * The `Boot` option should be set to primary.

Node ports should be created considering the **MAC address of the first
Interface** of the given Server Hardware.

.. note::
   Old versions of ironic using ``pre-allocation`` model (before Newton
   release) and nodes with `dynamic_allocation` flag disabled shall have their
   Server Profiles applied during node enrollment and can have their ports
   created using the `Virtual` MAC addresses provided on Server Profile
   application.

To tell ironic which NIC should be connected to the provisioning network, do::

  $ ironic port-create -n $NODE_UUID -a $MAC_ADDRESS

For more information on the enrollment process of an ironic node, see [4]_.

For more information on the definitions of ``Server Hardware``, ``Server
Profile``, ``Server Profile Template`` and other OneView entities, refer to
[1]_ or browse Help in your OneView appliance menu.

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
.. [4] Enrollment process of a node - http://docs.openstack.org/developer/ironic/deploy/install-guide.html#enrollment-process
.. [5] ironic install guide - http://docs.openstack.org/developer/ironic/deploy/install-guide.html#installation-guide
.. [6] Dynamic Allocation in OneView drivers - http://specs.openstack.org/openstack/ironic-specs/specs/not-implemented/oneview-drivers-dynamic-allocation.html
.. [7] ironic-oneviewd - https://pypi.python.org/pypi/ironic-oneviewd/
.. [8] ironic-oneview-cli - https://pypi.python.org/pypi/ironic-oneview-cli/
