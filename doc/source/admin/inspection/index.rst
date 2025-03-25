==================
In-Band Inspection
==================

In-band inspection involves booting a ramdisk on the target node and fetching
information directly from it. This process is more fragile and time-consuming
than the out-of-band inspection, but it is not vendor-specific and works
across a wide range of hardware.

In the 2023.2 "Bobcat" release series, Ironic received an experimental
implementation of in-band inspection that does not require the separate
ironic-inspector_ service.

.. note::
   The implementation described in this document is not 100% compatible with
   the previous one (based on ironic-inspector_). Check the documentation and
   the release notes for which features are currently available.

   Use :doc:`inspector` for production deployments of Ironic 2023.2 or earlier
   releases.

.. _ironic-inspector: https://pypi.org/project/ironic-inspector

.. toctree::
   :maxdepth: 2

   managed
   data
   hooks
   discovery
   pxe_filter
   migration

Inspection rules have now been migrate into Ironic as of 2025.1 "Epoxy"
release. This does not include support for reapplying inspection on
already stored data, nor does it support the ``"scope"`` field.

The scope field allowed a rule to be applied only to specific nodes with
matching scope value rather than all nodes where conditions are met.

:ironic-inspector-doc:`Inspection rules <user/usage.html#introspection-rules>`

Inspection Rules
----------------

.. _inspection_rules:

An inspection rule consists of conditions to check, and actions to run.
If conditions evaluate to true on the inspection data, then actions are
run on a node.

Ironic provides an API to manage such rules. There are also built-in rules
which are pre-saved and loaded from a YAML file and cannot be CRUD through
the API.

Available conditions and actions are defined by an extendedable set of
plugins.

Refer to the
`Ironic API reference for inspection rules <https://docs.openstack.org/api-ref/baremetal/#inspection_rules-inspection_rules>`_
for information on how to CRUD inspection rules.

Actions & Conditions
~~~~~~~~~~~~~~~~~~~~
Conditions and actions have the same base structure:

* ``op`` - operation: either boolean (conditions) or an action (actions).
* ``args`` - a list (in the sense of Python ``*args``)
  or a dict (in the sense of Python ``**kwargs``) with arguments.

Conditions
^^^^^^^^^^

Available conditions include:

* ``is-true(value)`` - Check if value evaluates to boolean True.
  This operator supports booleans, non-zero numbers and strings "yes", "true".
* ``is-false(value)`` - Check if value evaluates to boolean False.
  Supports booleans, zero, None and strings "no", "false".
* ``is-none(value)`` - Check if value is None.
* ``is-empty(value)`` - Check if value is None or an empty string,
  list or a dictionary.
* ``eq/lt/gt(*values, *, force_strings=False)`` - Check if all values are
  equal, less/greater than. If force_strings, all values will be converted
  to strings first before the check.
* ``in-net(address, subnet)`` - Check if the given address is in the provided
  subnet.
* ``contains(value, regex)`` - Check if the value contains the given regular
  expression.
* ``matches(value, regex)`` - Check if the value fully matches the given
  regular expression.
* ``one-of(value, values)`` - Check if the value is in the provided list.
  Similar to contains, but also works for non-string values.

To check for the inverse of any of these conditions, prefix the operator with
an exclamation mark (with an optional space) before the op. E.g.
``eq`` - ``!eq``.

Actions
^^^^^^^

Available actions include:

* ``fail(msg)`` - Fail inspection with the given message.
* ``set-plugin-data(path, value)`` - Set a value in the plugin data.
* ``extend-plugin-data(path, value, *, unique=False)`` - Treat a value in the
  plugin data as a list, append to it. If unique is True, do not append if the
  item exists.
* ``unset-plugin-data(path)`` - Unset a value in the plugin data.
* ``log(msg, level="info")`` - Write the message to the Ironic logs.
* ``set-attribute(path, value)`` - Set the given path
  (in the sense of JSON patch) to the value.
* ``extend-attribute(path, value, *, unique=False)`` - Treat the given path
  as a list, append to it.
* ``del-attribute(path)`` - Unset the given path. Fails on invalid node
  attributes, but does not fail on missing subdict fields.
* ``set-port-attribute(port_id, path, value)`` - Set value on the port
  identified by a MAC or a UUID.
* ``extend-port-attribute(port_id, path, value, *, unique=False)`` - Treat the
  given path on the port as a list, append to it.
* ``del-port-attribute(port_id, path)`` - Unset value on the port identified
  by a MAC or a UUID.

Loops
^^^^^
Both conditions and actions accept an optional ``loop`` argument of list of
items to iterate over for the same condition or action.

The ``loop`` field supports an Ansible-style loop (for reference, see
`Ansible loops documentation <https://docs.ansible.com/ansible/latest/playbook_guide/playbooks_loops.html>`_
).

In conditions, there's an additional (and optional) ``multiple`` field which is
only applicable when the loop field is present. It determines how the results
of all loop iterations are combined:

* ``any`` (default) - returns ``True`` if any iteration's result is ``True``
* ``all`` - returns ``True`` only if all iterations' results are ``True``
* ``first`` - returns the result of the first iteration only, skipping
  remaining iterations if the first is ``True``
* ``last`` - uses only the result from the last iteration, effectively
  ignoring previous iterations

For example, this condition check will return true if at any time of the
iteration, the 'system' is any of the models in the ``loop`` list:

.. code-block:: yaml

    - op: eq
    args: ["{inventory.system.product_name}", "{item}"]
    loop: ["HPE ProLiant DL380 Gen10", "PowerEdge R640", "Cisco UCS"]
    multiple: any

Whereas in actions, each iteration of the loop executes same action with the
current item value.

Example of setting multiple attributes using loop:

.. code-block:: yaml

    - op: set-attribute
      args: ["{item[path]}", "{item[value]}"]
      loop:
        - {path: "/driver_info/ipmi_username", value: "admin"}
        - {path: "/driver_info/ipmi_password", value: "password"}
        - {path: "/driver_info/ipmi_address", value: "{inventory[bmc_address]}"}

.. note::
   Both dot (``"driver_info.ipmi_username"``) and
   slash (``"driver_info/ipmi_username"``) notation paths are supported.

Variable Interpolation
^^^^^^^^^^^^^^^^^^^^^^

    {"action": "set-attribute", "path": "/driver_info/ipmi_address",
     "value": "{data[inventory][bmc_address]}"}

On a rule execution, values enclosed with braces, usually ``value``, ``msg``,
``address``, and ``subnet`` fields in both actions and conditions, will be
treated as replacement fields and formatted to a string using
`python string formatting notation <https://docs.python.org/3/library/string.html#formatspec>`_.

If the value of any of these keys is a dict or list, strings nested at any
level within the structure will be recursively formatted as well::

    {"action": "set-attribute", "path": "/properties/root_device",
     "value": {"serial": "{data[root_device][serial]}"}}

Configuration
-------------

In-band inspection is supported by all hardware types. The ``agent``
*inspect* interface has to be enabled to use it:

.. code-block:: ini

    [DEFAULT]
    enabled_inspect_interfaces = agent,no-inspect

You can make it the default if you want all nodes to use it automatically:

.. code-block:: ini

    [DEFAULT]
    default_inspect_interface = agent

Of course, you can configure it per node:

.. code-block:: console

   $ baremetal node set --inspect-interface agent <NODE>
