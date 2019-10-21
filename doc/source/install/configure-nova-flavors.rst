.. _flavor-creation:

Create flavors for use with the Bare Metal service
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

You'll need to create a special bare metal flavor in the Compute service.
The flavor is mapped to the bare metal node through the node's
``resource_class`` field (available starting with Bare Metal API version 1.21).
A flavor can request *exactly one* instance of a bare metal resource class.

Note that when creating the flavor, it's useful to add the ``RAM_MB`` and
``CPU`` properties as a convenience to users, although they are not used for
scheduling.  The ``DISK_GB`` property is also not used for scheduling, but is
still used to determine the root partition size.

#. Change these to match your hardware:

   .. code-block:: console

      $ RAM_MB=1024
      $ CPU=2
      $ DISK_GB=100

#. Create the bare metal flavor by executing the following command:

   .. code-block:: console

      $ openstack flavor create --ram $RAM_MB --vcpus $CPU --disk $DISK_GB \
        my-baremetal-flavor

   .. note:: You can add ``--id <id>`` to specify an ID for the flavor.

See the
:python-openstackclient-doc:`docs on this command <cli/command-objects/flavor.html#flavor-create>`
for other options that may be specified.

After creation, associate each flavor with one custom resource class. The name
of a custom resource class that corresponds to a node's resource class (in the
Bare Metal service) is:

* the bare metal node's resource class all upper-cased
* prefixed with ``CUSTOM_``
* all punctuation replaced with an underscore

For example, if the resource class is named ``baremetal-small``, associate
the flavor with this custom resource class via:

.. code-block:: console

      $ openstack flavor set --property resources:CUSTOM_BAREMETAL_SMALL=1 my-baremetal-flavor

Another set of flavor properties must be used to disable scheduling
based on standard properties for a bare metal flavor:

.. code-block:: console

      $ openstack flavor set --property resources:VCPU=0 my-baremetal-flavor
      $ openstack flavor set --property resources:MEMORY_MB=0 my-baremetal-flavor
      $ openstack flavor set --property resources:DISK_GB=0 my-baremetal-flavor

Example
-------

If you want to define a class of nodes called ``baremetal.with-GPU``, start
with tagging some nodes with it:

.. code-block:: console

      $ openstack --os-baremetal-api-version 1.21 baremetal node set $NODE_UUID \
        --resource-class baremetal.with-GPU

.. warning::
    It is possible to **add** a resource class to ``active`` nodes, but it is
    not possible to **replace** an existing resource class on them.

Then you can update your flavor to request the resource class instead of
the standard properties:

.. code-block:: console

      $ openstack flavor set --property resources:CUSTOM_BAREMETAL_WITH_GPU=1 my-baremetal-flavor
      $ openstack flavor set --property resources:VCPU=0 my-baremetal-flavor
      $ openstack flavor set --property resources:MEMORY_MB=0 my-baremetal-flavor
      $ openstack flavor set --property resources:DISK_GB=0 my-baremetal-flavor

Note how ``baremetal.with-GPU`` in the node's ``resource_class`` field becomes
``CUSTOM_BAREMETAL_WITH_GPU`` in the flavor's properties.

.. _scheduling-traits:

Scheduling based on traits
--------------------------

Starting with the Queens release, the Compute service supports scheduling based
on qualitative attributes using traits.  Starting with Bare Metal REST API
version 1.37, it is possible to assign a list of traits to each bare metal
node.  Traits assigned to a bare metal node will be assigned to the
corresponding resource provider in the Compute service placement API.

When creating a flavor in the Compute service, required traits may be specified
via flavor properties.  The Compute service will then schedule instances only
to bare metal nodes with all of the required traits.

Traits can be either standard or custom.  Standard traits are listed in the
`os_traits library <https://docs.openstack.org/os-traits/latest/>`_.  Custom
traits must meet the following requirements:

* prefixed with ``CUSTOM_``
* contain only upper case characters A to Z, digits 0 to 9, or underscores
* no longer than 255 characters in length

A bare metal node can have a maximum of 50 traits.

Example
^^^^^^^

To add the standard trait ``HW_CPU_X86_VMX`` and a custom trait
``CUSTOM_TRAIT1`` to a node:

.. code-block:: console

      $ openstack --os-baremetal-api-version 1.37 baremetal node add trait \
        $NODE_UUID CUSTOM_TRAIT1 HW_CPU_X86_VMX

Then, update the flavor to require these traits:

.. code-block:: console

      $ openstack flavor set --property trait:CUSTOM_TRAIT1=required my-baremetal-flavor
      $ openstack flavor set --property trait:HW_CPU_X86_VMX=required my-baremetal-flavor
