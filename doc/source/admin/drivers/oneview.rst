.. _oneview:

==============
OneView driver
==============

.. note::
   The `oneview` hardware type, along with related interfaces to support
   OneView, have been deprecated, and should be expected to be
   removed from ironic in the Stein cycle. Please see
   `storyboard <https://storyboard.openstack.org/#!/story/2001924>`_ for
   additional details.

Overview
========

HP OneView [1]_ is a single integrated platform, packaged as an appliance that
implements a software-defined approach to managing physical infrastructure.
The appliance supports scenarios such as deploying bare metal servers, for
instance. In this context, the ``HP OneView driver`` for ironic enables the
users of OneView to use ironic as a bare metal provider to their managed
physical hardware.

HPE OneView hardware is supported by the ``oneview`` hardware type.

To provide a bare metal instance there are four components involved in the
process:

* The ironic service
* The ironic-inspector service (if using hardware inspection)
* The ironic hardware type for OneView
* The hpOneView library
* The OneView appliance

The role of ironic is to serve as a bare metal provider to OneView's managed
physical hardware and to provide communication with other necessary OpenStack
services such as Nova and Glance. When ironic receives a boot request, it
works together with the ironic OneView driver to access a machine in OneView,
the ``hpOneView`` being responsible for the communication with the OneView
appliance.

From the Newton release on, OneView drivers enables a new feature called
**dynamic allocation** of nodes [6]_. In this model, the driver allocates
resources in OneView only at boot time, allowing idle resources in ironic
to be used by OneView users, enabling actual resource sharing among ironic
and OneView users.

Since OneView can claim nodes in ``available`` state at any time, a set of
tasks runs periodically to detect nodes in use by OneView. A node in use by
OneView is placed in ``manageable`` state and has maintenance mode set. Once
the node is no longer in use, these tasks will make place them back in
``available`` state and clear maintenance mode.

Prerequisites
=============

* ``OneView appliance`` is the HP physical infrastructure manager to be
  integrated with the OneView driver.

  Minimum version supported is 2.0.

* ``hpOneView`` is a python package containing a client to manage the
  communication between ironic and OneView.

  Install the ``hpOneView`` module to enable the communication. Minimum version
  required is 4.4.0 but it is recommended to install the most up-to-date
  version::

  $ pip install "hpOneView>=4.4.0"

* ``ironic-inspector`` if using hardware inspection.

Tested platforms
================

* The OneView appliance used for testing was the OneView 2.0.

* The Enclosure used for testing was the ``BladeSystem c7000 Enclosure G2``.

* The driver should work on HP Proliant Gen8 and Gen9 Servers supported by
  OneView 2.0 and above, or any hardware whose network can be managed by
  OneView's ServerProfile. It has been tested with the following servers:

  - Proliant BL460c Gen8
  - Proliant BL460c Gen9
  - Proliant BL465c Gen8
  - Proliant DL360 Gen9

  Notice that for the driver to work correctly with Gen8 and Gen9 DL servers
  in general, the hardware also needs to run version 4.2.3 of iLO, with
  Redfish enabled.

Hardware Interfaces
===================

The ``oneview`` hardware type supports the following hardware interfaces:

* boot
    Supports only ``pxe``. It can be enabled by using the
    ``[DEFAULT]enabled_boot_interfaces`` option in ``ironic.conf``
    as given below:

    .. code-block:: ini

        [DEFAULT]
        enabled_hardware_types = oneview
        enabled_boot_interfaces = pxe

* console
    Supports only ``no-console``. It can be enabled by using the
    ``[DEFAULT]enabled_console_interfaces``
    option in ``ironic.conf`` as given below:

    .. code-block:: ini

        [DEFAULT]
        enabled_hardware_types = oneview
        enabled_console_interfaces = no-console

* deploy
    Supports ``oneview-direct`` and ``oneview-iscsi``. The default is
    ``oneview-iscsi``. They can be enabled by using the
    ``[DEFAULT]enabled_deploy_interfaces`` option in ``ironic.conf``
    as given below:

    .. code-block:: ini

        [DEFAULT]
        enabled_hardware_types = oneview
        enabled_deploy_interfaces = oneview-iscsi,oneview-direct

* inspect
    Supports ``oneview`` and ``no-inspect``. The default is ``oneview``.
    They can be enabled by using the ``[DEFAULT]enabled_inspect_interfaces``
    option in ``ironic.conf`` as given below:

    .. code-block:: ini

        [DEFAULT]
        enabled_hardware_types = oneview
        enabled_inspect_interfaces = oneview,no-inspect

* management
    Supports only ``oneview``. It can be enabled by using the
    ``[DEFAULT]enabled_management_interfaces`` option in ``ironic.conf`` as
    given below:

    .. code-block:: ini

        [DEFAULT]
        enabled_hardware_types = oneview
        enabled_management_interfaces = oneview

* power
    Supports only ``oneview``. It can be enabled by using the
    ``[DEFAULT]enabled_power_interfaces`` option in ``ironic.conf`` as given
    below:

    .. code-block:: ini

        [DEFAULT]
        enabled_hardware_types = oneview
        enabled_power_interfaces = oneview

The ``oneview`` hardware type also supports the standard *network* and
*storage* interfaces.

Here is an example of putting multiple interfaces configuration at once:

.. code-block:: ini

    [DEFAULT]
    enabled_hardware_types = oneview
    enabled_deploy_interfaces = oneview-direct,oneview-iscsi
    enabled_inspect_interfaces = oneview
    enabled_power_interfaces = oneview
    enabled_management_interfaces = oneview

Deploy process with oneview-iscsi deploy interface
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

1. Admin configures the Proliant baremetal node to use ``oneview-iscsi``
   deploy interface.
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

Deploy process with oneview-direct deploy interface
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

1. Admin configures the Proliant baremetal node to use ``oneview-direct``
   deploy interface.
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

Hardware inspection
===================

The OneView driver for ironic has the ability to do hardware inspection.
Hardware inspection is the process of discovering hardware properties like
memory size, CPU cores, processor architecture and disk size, of a given
hardware. The OneView driver does in-band inspection, that involves booting a
ramdisk on the hardware and fetching information directly from it. For that,
your cloud controller needs to have the ``ironic-inspector`` component
[9]_ running and properly enabled in ironic's configuration file.

See [10]_ for more information on how to install and configure
``ironic-inspector``.

Registering a OneView node in ironic
====================================

Nodes configured to use the OneView driver should have the ``driver``
property set to ``oneview``. Considering our context, a node is the
representation of a ``Server Hardware`` in OneView,
and should be consistent with all its properties and related components, such
as ``Server Hardware Type``, ``Server Profile Template``, ``Enclosure Group``,
etc. In this case, to be enrolled, the node must have the following parameters:

* In ``driver_info``

  - ``server_hardware_uri``: URI of the ``Server Hardware`` on OneView.

* In ``properties/capabilities``

  - ``server_hardware_type_uri``: URI of the ``Server Hardware Type`` of the
    ``Server Hardware``.
  - ``server_profile_template_uri``: URI of the ``Server Profile Template`` used
    to create the ``Server Profile`` of the ``Server Hardware``.
  - ``enclosure_group_uri`` (optional): URI of the ``Enclosure Group`` of the
    ``Server Hardware``.

To enroll a node with the OneView driver using default values for the
supported hardware interfaces, do::

  $ openstack baremetal node create --driver oneview

To enroll a node with the OneView driver using specific hardware
interfaces, do::

  $ openstack baremetal node create --driver oneview \
      --deploy-interface oneview-direct \
      --power-interface oneview

To update the ``driver_info`` field of a newly enrolled OneView node, do::

  $ openstack baremetal node set $NODE_UUID --driver-info server_hardware_uri=$SH_URI

To update the ``properties/capabilities`` namespace of a newly enrolled
OneView node, do::

  $ openstack baremetal node set $NODE_UUID \
      --property capabilities=server_hardware_type_uri:$SHT_URI,enclosure_group_uri:$EG_URI,server_profile_template_uri=$SPT_URI

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

To tell ironic which NIC should be connected to the provisioning network, do::

  $ openstack baremetal port create --node $NODE_UUID $MAC_ADDRESS

For more information on the enrollment process of an ironic node, see
:ref:`enrollment`.

For more information on the definitions of ``Server Hardware``, ``Server
Profile``, ``Server Profile Template`` and other OneView entities, refer to
[1]_ or browse Help in your OneView appliance menu.

.. note::
   Ironic manages OneView machines either when they have
   a Server Profile applied by the driver or when they don't have any Server
   Profile. Trying to change the power state of the machine in OneView without
   first assigning a Server Profile will lead to allowing Ironic to revert the
   power state change. Ironic will NOT change the power state of machines
   which the Server Profile was applied by another OneView user.

3rd Party Tools
===============

In order to ease user manual tasks, which are often time-consuming, we provide
useful tools that work nicely with the OneView driver.

ironic-oneview-cli
~~~~~~~~~~~~~~~~~~

The ``ironic-oneView`` CLI is a command line interface for management tasks
involving OneView nodes. Its features include a facility to create of ironic
nodes with all required parameters for OneView nodes, creation of Nova flavors
for OneView nodes.

For more details on how Ironic-OneView CLI works and how to set it up, see
[8]_.

ironic-oneviewd
~~~~~~~~~~~~~~~

The ``ironic-oneviewd`` daemon monitors the ironic inventory of resources and
provides facilities to operators managing OneView driver deployments.

For more details on how Ironic-OneViewd works and how to set it up, see [7]_.

References
==========
.. [1] HP OneView - https://www.hpe.com/us/en/integrated-systems/software.html
.. [6] Dynamic Allocation in OneView drivers - https://specs.openstack.org/openstack/ironic-specs/specs/not-implemented/oneview-drivers-dynamic-allocation.html
.. [7] ironic-oneviewd - https://pypi.org/project/ironic-oneviewd/
.. [8] ironic-oneview-cli - https://pypi.org/project/ironic-oneview-cli/
.. [9] ironic-inspector - https://docs.openstack.org/ironic-inspector/latest/
.. [10] ironic-inspector install - https://docs.openstack.org/ironic-inspector/latest/install/index.html
