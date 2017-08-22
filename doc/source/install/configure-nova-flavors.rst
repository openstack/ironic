.. _flavor-creation:

Create flavors for use with the Bare Metal service
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Scheduling based on properties
==============================

You'll need to create a special bare metal flavor in the Compute service.
The flavor is mapped to the bare metal node through the hardware specifications.

#. Change these to match your hardware:

   .. code-block:: console

      $ RAM_MB=1024
      $ CPU=2
      $ DISK_GB=100
      $ ARCH={i686|x86_64}

#. Create the bare metal flavor by executing the following command:

   .. code-block:: console

      $ nova flavor-create my-baremetal-flavor auto $RAM_MB $DISK_GB $CPU

   .. note:: You can replace ``auto`` with your own flavor id.

#. Set the architecture as extra_specs information of the flavor. This
   will be used to match against the properties of bare metal nodes:

   .. code-block:: console

      $ nova flavor-key my-baremetal-flavor set cpu_arch=$ARCH

.. _scheduling-resource-classes:

Scheduling based on resource classes
====================================

As of the Pike release, a Compute service flavor is able to use the node's
``resource_class`` field (available starting with Bare Metal API version 1.21)
for scheduling, instead of the CPU, RAM, and disk properties defined in
the flavor. A flavor can request *exactly one* instance of a bare metal
resource class.

Start with creating the flavor in the same way as described in
`Scheduling based on properties`_. The ``CPU``, ``RAM_MB`` and ``DISK_GB``
values are not going to be used for scheduling, but the ``DISK_GB``
value will still be used to determine the root partition size.

After creation, associate each flavor with one custom resource class. The name
of a custom resource class that corresponds to a node's resource class (in the
Bare Metal service) is:

* the bare metal node's resource class all upper-cased
* prefixed with ``CUSTOM_``
* all punctuation replaced with an underscore

For example, if the resource class is named ``baremetal-small``, associate
the flavor with this custom resource class via:

.. code-block:: console

      $ nova flavor-key my-baremetal-flavor set resources:CUSTOM_BAREMETAL_SMALL=1

Another set of flavor properties should be used to disable scheduling
based on standard properties for a bare metal flavor:

.. code-block:: console

      $ nova flavor-key my-baremetal-flavor set resources:VCPU=0
      $ nova flavor-key my-baremetal-flavor set resources:MEMORY_MB=0
      $ nova flavor-key my-baremetal-flavor set resources:DISK_GB=0

.. warning::
   The last step will be mandatory in the Queens release, as the Compute
   service will stop providing standard resources for bare metal nodes.

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

      $ nova flavor-key my-baremetal-flavor set resources:CUSTOM_BAREMETAL_WITH_GPU=1
      $ nova flavor-key my-baremetal-flavor set resources:VCPU=0
      $ nova flavor-key my-baremetal-flavor set resources:MEMORY_MB=0
      $ nova flavor-key my-baremetal-flavor set resources:DISK_GB=0

Note how ``baremetal.with-GPU`` in the node's ``resource_class`` field becomes
``CUSTOM_BAREMETAL_WITH_GPU`` in the flavor's properties.
