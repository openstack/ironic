.. _oneview:

===============
OneView drivers
===============

Overview
========

HP OneView [1]_ is a single integrated platform, packaged as an appliance that
implements a software-defined approach to managing physical infrastructure.
The appliance supports scenarios such as deploying bare metal servers, for
instance. In this context, the ``HP OneView driver`` for Ironic enables the
users of OneView to use Ironic as a bare metal provider to their managed
physical hardware.

Currently there are two OneView drivers:

* ``iscsi_pxe_oneview``
* ``agent_pxe_oneview``

The ``iscsi_pxe_oneview`` and ``agent_pxe_oneview`` drivers implement the
core interfaces of an Ironic Driver [2]_, and use the ``python-oneviewclient``
[3]_ to provide communication between Ironic and OneView through OneView's
Rest API.

To provide a bare metal instance there are four components involved in the
process:

* Ironic service
* python-oneviewclient
* OneView appliance
* iscsi_pxe_oneview/agent_pxe_oneview driver

The role of Ironic is to serve as a bare metal provider to OneView's managed
physical hardware and to provide communication with other necessary OpenStack
services such as Nova and Glance. When Ironic receives a boot request, it
works together with the Ironic OneView driver to access a machine in OneView,
the ``python-oneviewclient`` being responsible for the communication with the
OneView appliance.

Prerequisites
=============

The following requirements apply for both ``iscsi_pxe_oneview`` and
``agent_pxe_oneview`` drivers:

* ``OneView appliance`` is the HP physical infrastructure manager to be
  integrated with the OneView drivers.

  Minimum version supported is 2.0.

* ``python-oneviewclient`` is a python package containing a client to manage
  the communication between Ironic and OneView.

  Install the ``python-oneviewclient`` module to enable the communication.
  Minimum version required is 2.0.2 but it is recommended to install the most
  up-to-date version.::

  $ pip install "python-oneviewclient<3.0.0,>=2.0.2"

Tested platforms
================

* The OneView appliance used for testing was the OneView 2.0.

* The Enclosure used for testing was the ``BladeSystem c7000 Enclosure G2``.

* The drivers should work on HP Proliant Gen8 and Gen9 Servers supported by
  OneView 2.0 and above, or any hardware whose network can be managed by
  OneView's ServerProfile. It has been tested with the following servers:

  - Proliant BL460c Gen8
  - Proliant BL465c Gen8
  - Proliant DL360 Gen9 (starting with python-oneviewclient 2.1.0)

  Notice here that to the driver work correctly with Gen8 and Gen9 DL servers
  in general, the hardware also needs to run version 4.2.3 of iLO, with Redfish.

Drivers
=======

iscsi_pxe_oneview driver
^^^^^^^^^^^^^^^^^^^^^^^^

Overview
~~~~~~~~

``iscsi_pxe_oneview`` driver uses PXEBoot for boot and ISCSIDeploy for deploy.

Configuring and enabling the driver
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

1. Add ``iscsi_pxe_oneview`` to the list of ``enabled_drivers`` in
   ``/etc/ironic/ironic.conf``. For example::

    enabled_drivers = iscsi_pxe_oneview

2. Update the [oneview] section of your ``ironic.conf`` file with your
   OneView credentials and CA certificate files information.

3. Restart the Ironic conductor service. For Ubuntu users, do::

    $ sudo service ironic-conductor restart

See [5]_ for more information.

Deploy process
~~~~~~~~~~~~~~

Here is an overview of the deploy process for this driver:

1. Admin configures the Proliant baremetal node to use ``iscsi_pxe_oneview``
   driver.
2. Ironic gets a request to deploy a Glance image on the baremetal node.
3. Driver sets the boot device to PXE.
4. Driver powers on the baremetal node.
5. Ironic downloads the deploy and user images from a TFTP server.
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

1. Add ``agent_pxe_oneview`` to the list of ``enabled_drivers`` in
   ``/etc/ironic/ironic.conf``. For example::

    enabled_drivers = fake,pxe_ssh,pxe_ipmitool,agent_pxe_oneview

2. Update the [oneview] section of your ``ironic.conf`` file with your
   OneView credentials and CA certificate files information.

3. Restart the Ironic conductor service. For Ubuntu users, do::

    $ service ironic-conductor restart

See [5]_ for more information.

Deploy process
~~~~~~~~~~~~~~

Here is an overview of the deploy process for this driver:

1. Admin configures the Proliant baremetal node to use ``agent_pxe_oneview``
   driver.
2. Ironic gets a request to deploy a Glance image on the baremetal node.
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

Registering a OneView node in Ironic
====================================

Nodes configured to use any of the OneView drivers should have the ``driver``
property set to ``iscsi_pxe_oneview`` or ``agent_pxe_oneview``. Considering
our context, a node is the representation of a ``Server Hardware`` in OneView,
and should be consistent with all its properties and related components, such
as ``Server Hardware Type``, ``Server Profile Template``, ``Enclosure Group``,
etc. In this case, to be enrolled, the node must have the following parameters:

* In ``driver_info``

  - ``server_hardware_uri``: URI of the Server Hardware on OneView.

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

In order to deploy, a Server Profile consistent with the Server Profile
Template of the node MUST be applied to the Server Hardware it represents.
Server Profile Templates and Server Profiles to be utilized for deployments
MUST have configuration such that its **first Network Interface** ``boot``
property is set to "Primary" and connected to Ironic's provisioning network.

To tell Ironic which NIC should be connected to the provisioning network, do::

  $ ironic port-create -n $NODE_UUID -a $MAC_ADDRESS

For more information on the enrollment process of an Ironic node, see [4]_.

For more information on the definitions of ``Server Hardware``,
``Server Profile``, ``Server Profile Template`` and many other OneView
entities, see [1]_ or browse Help in your OneView appliance menu.

References
==========
.. [1] HP OneView - http://www8.hp.com/us/en/business-solutions/converged-systems/oneview.html
.. [2] Driver interfaces - http://docs.openstack.org/developer/ironic/dev/architecture.html#drivers
.. [3] python-oneviewclient - https://pypi.python.org/pypi/python-oneviewclient
.. [4] Enrollment process of a node - http://docs.openstack.org/developer/ironic/deploy/install-guide.html#enrollment-process
.. [5] Ironic install guide - http://docs.openstack.org/developer/ironic/deploy/install-guide.html#installation-guide
