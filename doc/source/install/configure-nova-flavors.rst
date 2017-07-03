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

Scheduling based on resource classes
====================================

The Newton release of the Bare Metal service includes a field on the node
resource called ``resource_class``. This field is available in version 1.21 of
the Bare Metal service API.

In the future (Pike or Queens release), a Compute service flavor will use this
field for scheduling, instead of the CPU, RAM, and disk properties defined in
the flavor above. A flavor will require *exactly one* of some bare metal
resource class.

This work is still in progress (see `blueprint
custom-resource-classes-in-flavors`), and the syntax for the ``flavor-create``
call to associate flavors with resource classes is yet to be implemented.
According to the `custom resource classes specification`_, it will look
as follows:

.. code-block:: console

      $ nova flavor-key my-baremetal-flavor set resources:CUSTOM_<RESOURCE_CLASS>=1

where ``<RESOURCE_CLASS>`` is the resource class name in upper case with all
punctuation replaces with an underscore.

For example,

.. code-block:: console

      $ ironic --ironic-api-version=1.21 node-update $NODE_UUID \
        replace resource_class=baremetal.with-GPU
      $ nova flavor-key my-baremetal-flavor set resources:CUSTOM_BAREMETAL_WITH_CPU=1

Another set of extra_specs properties will be used to disable scheduling
based on standard properties for a bare metal flavor:

.. code-block:: console

      $ nova flavor-key my-baremetal-flavor set resources:VCPU=0
      $ nova flavor-key my-baremetal-flavor set resources:MEMORY_MB=0
      $ nova flavor-key my-baremetal-flavor set resources:DISK_GB=0

.. note::
   The last step will be required, as the Compute service will stop providing
   standard resources for bare metal nodes.

.. _blueprint custom-resource-classes-in-flavors: https://blueprints.launchpad.net/nova/+spec/custom-resource-classes-in-flavors
.. _custom resource classes specification: https://specs.openstack.org/openstack/nova-specs/specs/pike/approved/custom-resource-classes-in-flavors.html
