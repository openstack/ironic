.. _runbooks:

=================================
Runbooks for Cleaning & Servicing
=================================

Overview
========

The Runbook resource represents a collection of steps that define a
series of actions to be executed on a node during cleaning and servicing
operations. Runbooks enable users to perform simple and complex operations
in a consistent, predefined and automated manner.

A runbook is matched for a node if the runbook's name matches a trait in the
node. So, runbooks can be created to match already existing traits for select
nodes or the other way around; either way a valid runbook name must be unique
and follow the traits naming convention since that's the basis of association
with a node.

Hence, runbook names can be either standard or custom. Standard runbook names
are listed in the `os_traits library <https://docs.openstack.org/os-traits/latest/>`_.
Custom traits must be prefixed with ``CUSTOM_``, contain only upper case
characters A to Z, digits 0 to 9, or underscores and be no longer than 255
characters in length.

No two runbooks can have the same name, as runbook names must be unique
within the system.

Access Control for Runbooks
---------------------------

Runbooks implements a role-based access control model that determines who can
create, modify, and use them:

The ``owner`` and ``public`` fields determine a runbook's accessibility:

* If ``owner`` is non-null (``public`` is automatically false), the runbook is
  scoped to that project and only usable on nodes owned or leased by that
  project
* If ``owner`` is null and ``public`` is false, only system-scoped users can access
  or use the runbook
* If ``owner`` is null and ``public`` is true, any project can use the runbook on
  compatible nodes, but only system-scoped users can modify it

.. note::
   For design details and implementation specifics, please see the
   `Runbooks specification <https://specs.openstack.org/openstack/ironic-specs/specs/not-implemented/runbooks.html>`_.

Purpose of Trait Matching
-------------------------

The trait matching mechanism serves as an access control to ensure that
runbooks are only executed on pre-approved nodes.

When executing a runbook, you must explicitly specify which runbook to run.
Currently, there is no way to execute multiple runbooks on a single node with
one command. However, you can include all necessary steps in a single
comprehensive runbook if you need to perform multiple operations.

You can verify that a node has the required trait for a runbook::

    baremetal node trait list <node>

Refer to the `Ironic API reference for runbooks <https://docs.openstack.org/api-ref/baremetal/#runbooks-runbooks>`_
for information on how to create, and manage runbooks.

For more details about node cleaning and servicing operations, please see
:ref:`cleaning` and :ref:`servicing`.

Example Runbook
===============

.. code-block:: bash

    baremetal runbook create --name CUSTOM_FIRMWARE_UPGRADE \
      --steps '[
         {
            "interface": "management",
            "step": "reset_bios_to_default",
            "args": {},
            "order": 1
         },
         {
            "interface": "management",
            "step": "update_firmware",
            "args": {
               "firmware_url": "https://example.com/firmware.bin",
               "component": "bios"
            },
            "order": 2
         },
         {
            "interface": "management",
            "step": "reboot",
            "args": {},
            "order": 3
         }
      ]'

   The output of the create command would show the complete runbook details::

      +------------+---------------------------------------------------------------------------------------------------------+
      | Field      | Value                                                                                                   |
      +------------+---------------------------------------------------------------------------------------------------------+
      | created_at | 2025-03-12T14:16:26.054115+00:00                                                                        |
      | extra      | {}                                                                                                      |
      | name       | CUSTOM_FIRMWARE_UPGRADE                                                                                 |
      | owner      | None                                                                                                    |
      | public     | False                                                                                                   |
      | steps      | [{'interface': 'management', 'step': 'reset_bios_to_default', 'args': {}, 'order': 1}, {'interface':    |
      |            | 'management', 'step': 'update_firmware', 'args': {'firmware_url': 'https://example.com/firmware.bin',   |
      |            | 'component': 'bios'}, 'order': 2}, {'interface': 'management', 'step': 'reboot', 'args': {}, 'order':   |
      |            | 3}]                                                                                                     |
      | updated_at | None                                                                                                    |
      | uuid       | 160ff684-5216-4874-9a61-775c3a17c892                                                                    |
      +------------+---------------------------------------------------------------------------------------------------------+

Cleaning and Servicing
======================

Once a runbook is created and associated with a node via matching traits,
it can be used in place of explicit cleaning or servicing steps.

For cleaning operations::

    # Using a runbook name
    baremetal node clean --runbook CUSTOM_FIRMWARE_UPGRADE node-0

    # Or using a runbook UUID
    baremetal node clean --runbook 160ff684-5216-4874-9a61-775c3a17c892 node-0

For servicing operations::

    # Using a runbook name
    baremetal node service --runbook CUSTOM_FIRMWARE_UPGRADE node-0

    # Or using a runbook UUID
    baremetal node service --runbook 160ff684-5216-4874-9a61-775c3a17c892 node-0

These commands will execute all the steps defined in the runbook in the
specified order.
