.. _adoption:

=============
Node adoption
=============

Overview
========
As part of hardware inventory lifecycle management, it is not an
unreasonable need to have the capability to be able to add hardware
that should be considered "in-use" by the Bare Metal service,
that may have been deployed by another Bare Metal service
installation or deployed via other means.

As such, the node adoption feature allows a user to define a node
as ``active`` while skipping the ``available`` and ``deploying``
states, which will prevent the node from being seen by the Compute
service as ready for use.

This feature is leveraged as part of the state machine workflow,
where a node in ``manageable`` can be moved to ``active`` state
via the provision_state verb ``adopt``.  To view the state
transition capabilities, please see :ref:`states`.

.. NOTE::
    For deployments using Ironic in conjunction with Nova, Ironic's
    node adoption feature is not suitable. If you need to adopt production
    nodes into Ironic **and** Nova, you can find a high-level recipe in
    :ref:`adoption_with_nova`.

How it works
============

A node initially enrolled begins in the ``enroll`` state. An operator
must then move the node to ``manageable`` state, which causes the node's
``power`` interface to be validated. Once in ``manageable`` state,
an operator can then explicitly choose to adopt a node.

Adoption of a node results in the validation of its ``boot`` interface,
and upon success the process leverages what is referred to as the "takeover"
logic. The takeover process is intended for conductors to take over the
management of nodes for a conductor that has failed.

The takeover process involves the deploy interface's ``prepare`` and
``take_over`` methods being called. These steps take specific actions such as
downloading and staging the deployment kernel and ramdisk, ISO image, any
required boot image, or boot ISO image and then places any PXE or virtual
media configuration necessary for the node should it be required.

The adoption process makes no changes to the physical node, with the
exception of operator supplied configurations where virtual media is
used to boot the node under normal circumstances. An operator should
ensure that any supplied configuration defining the node is sufficient
for the continued operation of the node moving forward.

Possible Risk
=============

The main risk with this feature is that supplied configuration may ultimately
be incorrect or invalid which could result in potential operational issues:

* ``rebuild`` verb - Rebuild is intended to allow a user to re-deploy the node
  to a fresh state. The risk with adoption is that the image defined when an
  operator adopts the node may not be the valid image for the pre-existing
  configuration.

  If this feature is utilized for a migration from one deployment to another,
  and pristine original images are loaded and provided, then ultimately the
  risk is the same with any normal use of the ``rebuild`` feature, the server
  is effectively wiped.

* When deleting a node, the deletion or cleaning processes may fail if the
  incorrect deployment image is supplied in the configuration as the node
  may NOT have been deployed with the supplied image and driver or
  compatibility issues may exist as a result.

  Operators will need to be cognizant of that possibility and should plan
  accordingly to ensure that deployment images are known to be compatible
  with the hardware in their environment.

* Networking - Adoption will assert no new networking configuration to the
  newly adopted node as that would be considered modifying the node.

  Operators will need to plan accordingly and have network configuration
  such that the nodes will be able to network boot.

How to use
==========

.. NOTE::
   The power state that the ironic-conductor observes upon the first
   successful power state check, as part of the transition to the
   ``manageable`` state will be enforced with a node that has been adopted.
   This means a node that is in ``power off`` state will, by default, have
   the power state enforced as ``power off`` moving forward, unless an
   administrator actively changes the power state using the Bare Metal
   service.

Requirements
------------

Requirements for use are essentially the same as to deploy a node:

* Sufficient driver information to allow for a successful
  power management validation.

* Sufficient instance_info to pass deploy interface preparation.

Each driver may have additional requirements dependent upon the
configuration that is supplied. An example of this would be defining
a node to always boot from the network, which will cause the conductor
to attempt to retrieve the pertinent files. Inability to do so will
result in the adoption failing, and the node being placed in the
``adopt failed`` state.

Example
-------

This is an example to create a new node, named ``testnode``, with
sufficient information to pass basic validation in order to be taken
from the ``manageable`` state to ``active`` state::

    # Explicitly set the client API version environment variable to
    # 1.17, which introduces the adoption capability.
    export OS_BAREMETAL_API_VERSION=1.17

    baremetal node create --name testnode \
        --driver ipmi \
        --driver-info ipmi_address=<ip_address> \
        --driver-info ipmi_username=<username> \
        --driver-info ipmi_password=<password> \
        --driver-info deploy_kernel=<deploy_kernel_id_or_url> \
        --driver-info deploy_ramdisk=<deploy_ramdisk_id_or_url>

    baremetal port create <node_mac_address> --node <node_uuid>

    baremetal node set testnode \
        --instance-info image_source="http://localhost:8080/blankimage" \
        --instance-info capabilities="{\"boot_option\": \"local\"}"

    baremetal node manage testnode --wait

    baremetal node adopt testnode --wait

.. NOTE::
   In the above example, the image_source setting must reference a valid
   image or file, however that image or file can ultimately be empty.

.. NOTE::
   The above example utilizes a capability that defines the boot operation
   to be local. It is recommended to define the node as such unless network
   booting is desired.

.. NOTE::
   The above example will fail a re-deployment as a fake image is
   defined and no instance_info/image_checksum value is defined.
   As such any actual attempt to write the image out will fail as the
   image_checksum value is only validated at time of an actual
   deployment operation.

.. NOTE::
   A user may wish to assign an instance_uuid to a node, which could be
   used to match an instance in the Compute service. Doing so is not
   required for the proper operation of the Bare Metal service.

   baremetal node set <node name or uuid> --instance-uuid <uuid>

.. NOTE::
   In Newton, coupled with API version 1.20, the concept of a
   network_interface was introduced. A user of this feature may wish to
   add new nodes with a network_interface of ``noop`` and then change
   the interface at a later point and time.

Troubleshooting
===============

Should an adoption operation fail for a node, the error that caused the
failure will be logged in the node's ``last_error`` field when viewing the
node. This error, in the case of node adoption, will largely be due to
failure of a validation step. Validation steps are dependent
upon what driver is selected for the node.

Any node that is in the ``adopt failed`` state can have the ``adopt`` verb
re-attempted.  Example::

  baremetal node adopt <node name or uuid>

If a user wishes to abort their attempt at adopting, they can then move
the node back to ``manageable`` from ``adopt failed`` state by issuing the
``manage`` verb.  Example::

  baremetal node manage <node name or uuid>

If all else fails the hardware node can be removed from the Bare Metal
service.  The ``node delete`` command, which is **not** the same as setting
the provision state to ``deleted``, can be used while the node is in
``adopt failed`` state. This will delete the node without cleaning
occurring to preserve the node's current state. Example::

  baremetal node delete <node name or uuid>

.. _adoption_with_nova:

Adoption with Nova
==================

Since there is no mechanism to create bare metal instances in Nova when nodes
are adopted into Ironic, the node adoption feature described above cannot be
used to add in production nodes to deployments which use Ironic together with
Nova.

One option to add in production nodes to an Ironic/Nova deployment is to use
the fake drivers. The overall idea is that for Nova the nodes are instantiated
normally to ensure the instances are properly created in the compute project
while Ironic does not touch them.

Here are some high level steps to be used as a guideline:

* create a bare metal flavor and a hosting project for the instances
* enroll the nodes into Ironic, create the ports, move them to manageable
* change the hardware type and the interfaces to fake drivers
* provide the nodes to make them available
* one by one, add the nodes to the placement aggregate and create instances
* change the hardware type and the interfaces back to the real ones

Make sure you change the drivers to the fake ones **before** providing the
nodes as cleaning will otherwise wipe your production servers!

The reason to make all nodes available and manage access via the aggregate is
that this is much faster than providing nodes one by one and relying on the
resource tracker to find them. Enabling them one by one is required to make
sure the instance name and the (pre-adoption) name of the server match.

The above recipe does not cover Neutron which, depending on your deployment,
may need to be handled in addition.
