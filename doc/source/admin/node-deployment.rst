===============
Node Deployment
===============

.. contents::
  :depth: 2

.. _node-deployment-deploy-steps:

Overview
========

Node deployment is performed by the Bare Metal service to prepare a node for
use by a workload.  The exact work flow used depends on a number of factors,
including the hardware type and interfaces assigned to a node.

Deploy Steps
============

The Bare Metal service implements deployment by collecting a list of deploy
steps to perform on a node from the Power, Deploy, Management, BIOS, and RAID
interfaces of the driver assigned to the node. These steps are then ordered by
priority and executed on the node when the node is moved to the ``deploying``
state.

Nodes move to the ``deploying`` state when attempting to move to the ``active``
state (when the hardware is prepared for use by a workload).  For a full
understanding of all state transitions into deployment, please see
:doc:`../contributor/states`.

The Bare Metal service added support for deploy steps in the Rocky release.

Order of execution
------------------

Deploy steps are ordered from higher to lower priority, where a larger integer
is a higher priority. If the same priority is used by deploy steps on different
interfaces, the following resolution order is used: Power, Management, Deploy,
BIOS, and RAID interfaces.

.. _node-deployment-core-steps:

Agent steps
-----------

All deploy interfaces based on ironic-python-agent (i.e. ``direct``, ``iscsi``
and ``ansible`` and any derivatives) expose the following deploy steps:

``deploy.deploy`` (priority 100)
  In this step the node is booted using a provisioning image, and the user
  image is written to the node's disk.
``deploy.tear_down_agent`` (priority 40)
  In this step the provisioning image is shut down.
``deploy.switch_to_tenant_network`` (priority 30)
  In this step networking for the node is switched from provisioning to
  tenant networks.
``deploy.boot_instance`` (priority 20)
  In this step the node is booted into the user image.

Accordingly, the following priority ranges can be used for custom deploy steps:

> 100
  Out-of-band steps to run before deployment.
41 to 59
  In-band steps to run after the image is written the bootloader is installed.
21 to 39
  Out-of-band steps to run after the provisioning image is shut down.
1 to 19
  Any steps that are run when the user instance is already running.

Direct deploy
^^^^^^^^^^^^^

The :ref:`direct-deploy` interface splits the ``deploy.deploy`` step into:


``deploy.deploy`` (priority 100)
  In this step the node is booted using a provisioning image.
``deploy.write_image`` (priority 80)
  A combination of an out-of-band and in-band step that downloads and writes
  the image to the node. The step is executed asynchronously by the ramdisk.
``deploy.prepare_instance_boot`` (priority 60)
  In this step the boot device is configured and the bootloader is installed.

Additional priority ranges can be used for custom deploy steps:

81 to 99
  In-band deploy steps to run before the image is written.
61 to 79
  In-band deploy steps to run after the image is written but before the
  bootloader is installed.

Other deploy interfaces
^^^^^^^^^^^^^^^^^^^^^^^

Priorities 60 to 99 are currently reserved and should not be used.

.. TODO(dtantsur): update once iscsi and ansible are converted

Writing a Deploy Step
---------------------

Please refer to :doc:`/contributor/deploy-steps`.

FAQ
---

What deploy step is running?
^^^^^^^^^^^^^^^^^^^^^^^^^^^^
To check what deploy step the node is performing or attempted to perform and
failed, run the following command; it will return the value in the node's
``driver_internal_info`` field::

    openstack baremetal node show $node_ident -f value -c driver_internal_info

The ``deploy_steps`` field will contain a list of all remaining steps with
their priorities, and the first one listed is the step currently in progress or
that the node failed before going into ``deploy failed`` state.

Troubleshooting
---------------
If deployment fails on a node, the node will be put into the ``deploy failed``
state until the node is deprovisioned.  A deprovisioned node is moved to the
``available`` state after the cleaning process has been performed successfully.

Strategies for determining why a deploy step failed include checking the ironic
conductor logs, checking logs from the ironic-python-agent that have been
stored on the ironic conductor, or performing general hardware troubleshooting
on the node.

Deploy Templates
================

Starting with the Stein release, with Bare Metal API version 1.55, deploy
templates offer a way to define a set of one or more deploy steps to be
executed with particular sets of arguments and priorities.

Each deploy template has a name, which must be a valid trait.  Traits can be
either standard or custom.  Standard traits are listed in the
:os-traits-doc:`os_traits library <>`.  Custom traits must
meet the following requirements:

* prefixed with ``CUSTOM_``
* contain only upper case characters A to Z, digits 0 to 9, or underscores
* no longer than 255 characters in length

Deploy step format
------------------

An invocation of a deploy step is defined in a deploy template as follows::

    {
        "interface": "<name of the driver interface>",
        "step": "<name of the step>",
        "args": {
            "<arg1>": "<value1>",
            "<arg2>": "<value2>"
        },
        "priority": <priority of the step>
    }

A deploy template contains a list of one or more such steps. Each combination
of `interface` and `step` may only be specified once in a deploy template.

Matching deploy templates
-------------------------

During deployment, if any of the traits in a node's ``instance_info.traits``
field match the name of a deploy template, then the steps from that deploy
template will be added to the list of steps to be executed by the node.

When using the Compute service, any traits in the instance's flavor properties
or image properties are stored in ``instance_info.traits`` during deployment.
See :ref:`scheduling-traits` for further information on how traits are used for
scheduling when the Bare Metal service is used with the Compute service.

Note that there is no ongoing relationship between a node and any templates
that are matched during deployment. The set of matching deploy templates is
checked at deployment time. Any subsequent updates to or deletion of those
templates will not be reflected in the node's configuration unless it is
redeployed or rebuilt.  Similarly, if a node is rebuilt and the set of matching
deploy templates has changed since the initial deployment, then the resulting
configuration of the node may be different from the initial deployment.

Overriding default deploy steps
-------------------------------

A deploy step is enabled by default if it has a non-zero default priority.
A default deploy step may be overridden in a deploy template. If the step's
priority is a positive integer it will be executed with the specified priority
and arguments. If the step's priority is zero, the step will not be executed.

If a `core deploy step <node-deployment-core-steps>`_ is included in a
deploy template, it can only be assigned a priority of zero to disable it.

Creating a deploy template via API
----------------------------------

A deploy template can be created using the Bare Metal API::

    POST /v1/deploy_templates

Here is an example of the body of a request to create a deploy template with a
single step:

.. code-block:: json

   {
       "name": "CUSTOM_HYPERTHREADING_ON",
       "steps": [
           {
               "interface": "bios",
               "step": "apply_configuration",
               "args": {
                   "settings": [
                       {
                           "name": "LogicalProc",
                           "value": "Enabled"
                       }
                   ]
               },
               "priority": 150
           }
       ]
   }

Further information on this API is available `here
<https://docs.openstack.org/api-ref/baremetal/index.html?expanded=create-deploy-template-detail#create-deploy-template>`__.

Creating a deploy template via "openstack baremetal" client
-----------------------------------------------------------

A deploy template can be created via the ``openstack baremetal deploy template
create`` command, starting with ``python-ironicclient`` 2.7.0.

The argument ``--steps`` must be specified. Its value is one of:

- a JSON string
- path to a JSON file whose contents are passed to the API
- '-', to read from stdin. This allows piping in the deploy steps.

Example of creating a deploy template with a single step using a JSON string:

.. code-block:: console

   openstack baremetal deploy template create \
       CUSTOM_HYPERTHREADING_ON \
       --steps '[{"interface": "bios", "step": "apply_configuration", "args": {"settings": [{"name": "LogicalProc", "value": "Enabled"}]}, "priority": 150}]'

Or with a file:

.. code-block:: console

   openstack baremetal deploy template create \
       CUSTOM_HYPERTHREADING_ON \
       ---steps my-deploy-steps.txt

Or with stdin:

.. code-block:: console

   cat my-deploy-steps.txt | openstack baremetal deploy template create \
       CUSTOM_HYPERTHREADING_ON \
       --steps -

Example of use with the Compute service
---------------------------------------

.. note:: The deploy steps used in this example are for example purposes only.

In the following example, we first add the trait ``CUSTOM_HYPERTHREADING_ON``
to the node represented by ``$node_ident``:

.. code-block:: console

   openstack baremetal node add trait $node_ident CUSTOM_HYPERTHREADING_ON

We also update the flavor ``bm-hyperthreading-on`` in the Compute
service with the following property:

.. code-block:: console

    openstack flavor set --property trait:CUSTOM_HYPERTHREADING_ON=required bm-hyperthreading-on

Creating a Compute instance with this flavor will ensure that the instance is
scheduled only to Bare Metal nodes with the ``CUSTOM_HYPERTHREADING_ON`` trait.

We could then create a Bare Metal deploy template with the name
``CUSTOM_HYPERTHREADING_ON`` and a deploy step that enables Hyperthreading:

.. code-block:: json

   {
       "name": "CUSTOM_HYPERTHREADING_ON",
       "steps": [
           {
               "interface": "bios",
               "step": "apply_configuration",
               "args": {
                   "settings": [
                       {
                           "name": "LogicalProc",
                           "value": "Enabled"
                       }
                   ]
               },
               "priority": 150
           }
       ]
   }

When an instance is created using the ``bm-hyperthreading-on`` flavor, then the
deploy steps of deploy template ``CUSTOM_HYPERTHREADING_ON`` will be executed
during the deployment of the scheduled node, causing Hyperthreading to be
enabled in the node's BIOS configuration.

To make this example more dynamic, let's add a second trait
``CUSTOM_HYPERTHREADING_OFF`` to the node:

.. code-block:: console

   openstack baremetal node add trait $node_ident CUSTOM_HYPERTHREADING_OFF

We could also update a second flavor, ``bm-hyperthreading-off``, with the
following property:

.. code-block:: console

    openstack flavor set --property trait:CUSTOM_HYPERTHREADING_OFF=required bm-hyperthreading-off

Finally, we create a deploy template with the name
``CUSTOM_HYPERTHREADING_OFF`` and a deploy step that disables Hyperthreading:

.. code-block:: json

   {
       "name": "CUSTOM_HYPERTHREADING_OFF",
       "steps": [
           {
               "interface": "bios",
               "step": "apply_configuration",
               "args": {
                   "settings": [
                       {
                           "name": "LogicalProc",
                           "value": "Disabled"
                       }
                   ]
               },
               "priority": 150
           }
       ]
   }

Creating a Compute instance with the ``bm-hyperthreading-off`` instance will
cause the scheduled node to have Hyperthreading disabled in the BIOS during
deployment.

We now have a way to create Compute instances with different configurations, by
choosing between different Compute flavors, supported by a single Bare Metal
node that is dynamically configured during deployment.
