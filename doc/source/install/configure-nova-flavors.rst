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

The Newton release of the Bare Metal service includes a field on the node
resource called ``resource_class``. This field is available in version 1.21 of
the Bare Metal service API. Starting with the Pike release, this field has
to be populated for all nodes, as explained in :doc:`enrollment`.

As of the Pike release, a Compute service flavor is able to use this field
for scheduling, instead of the CPU, RAM, and disk properties defined in
the flavor above. A flavor can request *exactly one* instance of a bare metal
resource class.

To achieve that, the flavors, created as described in `Scheduling based on
properties`_, have to be associated with one custom resource class each.
A name of the custom resource class is the name of node's resource class, but
upper-cased, with ``CUSTOM_`` prefix prepended, and all punctuation replaced
with an underscore:

.. code-block:: console

      $ nova flavor-key my-baremetal-flavor set resources:CUSTOM_<RESOURCE_CLASS>=1

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

      $ ironic --ironic-api-version=1.21 node-update $NODE_UUID \
        replace resource_class=baremetal.with-GPU

.. warning::
    It is possible to **add** a resource class to ``active`` nodes, but it is
    not possiblre to **replace** an existing resource class on them.

Then you can update your flavor to request the resource class instead of
the standard properties:

.. code-block:: console

      $ nova flavor-key my-baremetal-flavor set resources:CUSTOM_BAREMETAL_WITH_GPU=1
      $ nova flavor-key my-baremetal-flavor set resources:VCPU=0
      $ nova flavor-key my-baremetal-flavor set resources:MEMORY_MB=0
      $ nova flavor-key my-baremetal-flavor set resources:DISK_GB=0

Note how ``baremetal.with-GPU`` in the node's ``resource_class`` field becomes
``CUSTOM_BAREMETAL_WITH_GPU`` in the flavor's properties.
