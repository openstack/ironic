.. _servicing:

==============
Node servicing
==============

Overview
========

In order to better enable operators to modify existing nodes, Ironic has
introduced the model of Node Servicing, where you can take a node in
``active`` state, modify it using steps similar to Deploy Steps or manual
cleaning through the Cleaning subsystem.

For more information on cleaning, please see :ref:`cleaning`.

Major differences
=================

Service steps do not contain an automatic execution model, which is intrinisc
to the standard deployment and "automated" cleaning workflows. This *may*
change at some point in the future.

This also means that while a priority value *can* be supplied, it is not
presently utilized.

Similarities to Cleaning and Deployment
=======================================

Similar to Clean and Deploy steps, when invoked an operator can validate
the curent running steps by viewing the ``driver_internal_info`` field
looking for a ``service_steps`` field. The *current* step being executed
can be viewed using the baremetal node ``service_step`` field, which is a
top level field.

Service steps are internally decorated on driver interface methods utilizing
decorator. This means service steps do not *automatically* expose clean and
deploy steps to be executed at any time. The Ironic development team took a
cautious and intentional approach behind methods which are decorated. Besides,
some clean and deployment steps are geared explicitly for operating in
that mode, and would not be suitable to be triggered outside of the
original workflow it was designed for use in.

Available Steps
===============


Executing Service Steps
=======================

In order for manual cleaning to work, you may need to configure a
`Servicing Network`_.

Starting manual cleaning via API
--------------------------------

Servicing can only be performed when a node is in the ``active``
provision state. The REST API request to initiate it is available in
API version 1.87 and higher::

    PUT /v1/nodes/<node_ident>/states/provision

(Additional information is available `here <https://docs.openstack.org/api-ref/baremetal/index.html?expanded=change-node-provision-state-detail#change-node-provision-state>`_.)

This API will allow operators to put a node directly into ``servicing``
provision state from ``active`` provision state via 'target': 'service'.
The PUT will also require the argument 'service_steps' to be specified. This
is an ordered list of steps. A step is represented by a
dictionary (JSON), in the form::

  {
      "interface": "<interface>",
      "step": "<name of step>",
      "args": {"<arg1>": "<value1>", ..., "<argn>": <valuen>}
  }

The 'interface' and 'step' keys are required for all steps. If a cleaning step
method takes keyword arguments, the 'args' key may be specified. It
is a dictionary of keyword variable arguments, with each keyword-argument entry
being <name>: <value>.

If any step is missing a required keyword argument, servicing will not be
performed and the node will be put in ``service failed`` provision state
with an appropriate error message.

If, during the servicing process, a service step determines that it has
incorrect keyword arguments, all earlier steps will be performed and then the
node will be put in ``service failed`` provision state with an appropriate
error message.

An example of the request body for this API::

  {
    "target":"service",
    "sevice_steps": [{
      "interface": "raid",
      "step": "apply_configuration",
      "args": {"create_nonroot_volumes": True}
    },
    {
      "interface": "vendor",
      "step": "send_raw"
      "args": {"raw_bytes": "0x00 0x00 0x00 0x00"}
    }]
  }

In the above example, the node's RAID interface would apply the set RAID
configuration, and then the vendor interface's ``send_raw`` step would be
called to send a raw command to the BMC. Please note, ``send_raw`` is only
available for the ``ipmi`` hardware type.

Starting servicing via "openstack baremetal" CLI
------------------------------------------------

Servicing is available via the ``baremetal node service`` command,
starting with Bare Metal API version 1.87.

The argument ``--service-steps`` must be specified. Its value is one of:

- a JSON string
- path to a JSON file whose contents are passed to the API
- '-', to read from stdin. This allows piping in the clean steps.
  Using '-' to signify stdin is common in Unix utilities.

Examples of doing this with a JSON string::

    baremetal node service <node> \
        --clean-steps '[{"interface": "deploy", "step": "example_task"}]'

    baremetal node service <node> \
        --service-steps '[{"interface": "deploy", "step": "example_task"}]'

Or with a file::

    baremetal node service <node> \
        --service-steps my-service-steps.txt

Or with stdin::

    cat my-clean-steps.txt | baremetal node service <node> \
        --service-steps -

Available Steps in Ironic
-------------------------

ipmi hardware type
~~~~~~~~~~~~~~~~~~

vendor.send_raw
^^^^^^^^^^^^^^^

This step is covered in the :doc:`/admin/drivers/ipmitool` documentation
and is usable as a service step in addition to a deploy step.

redfish hardware type
~~~~~~~~~~~~~~~~~~~~~

bios.apply_configuration
^^^^^^^^^^^^^^^^^^^^^^^^

This is covered in the :ref:`bios` configuration documentation as it
started as a cleaning step. It is a standardized cross-interface name.

management.update_firmware
^^^^^^^^^^^^^^^^^^^^^^^^^^

This step is covered in the :doc:`/admin/drivers/redfish` and is intended
to facilitate firmware updates via the BMC.

raid.apply_configuration
^^^^^^^^^^^^^^^^^^^^^^^^

This step is covered in the :doc:`/admin/drivers/redfish` and is intended
to facilitate applying raid configuration.

raid.delete_configuration
^^^^^^^^^^^^^^^^^^^^^^^^^

This step is covered in the :doc:`/admin/drivers/redfish` and is intended
to delete configuration.

Agent
~~~~~

raid.apply_configuration
^^^^^^^^^^^^^^^^^^^^^^^^

This is the standardized RAID passthrough interface for the agent, and can
be leveraged like other RAID interfaces.


Available steps in Ironic-Python-Agent
--------------------------------------

.. note::
   Steps available from the agent will be populated once support has
   merged in the agent to expose the steps to the ironic deployment.

Servicing Network
=================

If you are using the Neutron DHCP provider (the default) you will also need to
ensure you have configured a servicing network. This network will be used to
boot the ramdisk for in-band service operations. This setting is configured
utilizing the ``[neutron]servicing_network`` configuration parameter.
