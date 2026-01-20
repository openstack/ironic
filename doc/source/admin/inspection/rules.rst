================
Inspection Rules
================

Inspection rules have now been migrated into Ironic as of the 2025.1 "Epoxy"
release. This does not include support for reapplying inspection on already
stored data, nor does it support the ``"scope"`` field.

The scope field allowed a rule to be applied only to specific nodes with
matching scope value rather than all nodes where conditions are met.

An inspection rule consists of conditions to check, and actions to run.
If conditions evaluate to true on the inspection data, then actions are
run on a node.

Ironic provides an API to manage such rules. There are also built-in rules
which are pre-saved and loaded from a YAML file and cannot be CRUD through
the API.

Available conditions and actions are defined by an extendable set of plugins.

Refer to the
`Ironic API reference for inspection rules <https://docs.openstack.org/api-ref/baremetal/#inspection-rules-inspection-rules>`_
for information on how to CRUD inspection rules.

Actions & Conditions
--------------------

Conditions and actions have the same base structure:

* ``op`` - operation: either boolean (conditions) or an action (actions).
* ``args`` - a list (in the sense of Python ``*args``)
  or a dict (in the sense of Python ``**kwargs``) with arguments.

Conditions
~~~~~~~~~~

Available conditions include:

* ``eq(*values, *, force_strings=False)`` - Check if all values are
  equal. If force_strings, all values will be converted
  to strings first before the check.
* ``lt(*values, *, force_strings=False)`` - Check if all values are
  less than. If force_strings, all values will be converted
  to strings first before the check.
* ``gt(*values, *, force_strings=False)`` - Check if all values are
  greater than. If force_strings, all values will be converted
  to strings first before the check.
* ``is-empty(value)`` - Check if value is None or an empty string,
  list or a dictionary.
* ``in-net(address, subnet)`` - Check if the given address is in the provided
  subnet.
* ``matches(value, regex)`` - Check if the value fully matches the given
  regular expression.
* ``contains(value, regex)`` - Check if the value contains the given regular
  expression.
* ``one-of(value, values)`` - Check if the value is in the provided list.
  Similar to contains, but also works for non-string values.
* ``is-none(value)`` - Check if value is None.
* ``is-true(value)`` - Check if value evaluates to boolean True.
  This operator supports booleans, non-zero numbers and strings "yes", "true".
* ``is-false(value)`` - Check if value evaluates to boolean False.
  Supports booleans, zero, None and strings "no", "false".

To check for the inverse of any of these conditions, prefix the operator with
an exclamation mark (with an optional space) before the op. E.g.
``eq`` - ``!eq``.

Actions
~~~~~~~

Available actions include:

* ``fail(msg)`` - Fail inspection with the given message.
* ``log(msg, level="info")`` - Write the message to the Ironic logs.
* ``set-attribute(path, value)`` - Set the given path
  (in the sense of JSON patch) to the value.
* ``extend-attribute(path, value, *, unique=False)`` - Treat the given path
  as a list, append to it.
* ``del-attribute(path)`` - Unset the given path. Fails on invalid node
  attributes, but does not fail on missing subdict fields.
* ``set-capability(name, value)`` - Adds the given node capability with
  the supplied value.
* ``unset-capability(name)`` - Unsets the given node capability.
* ``add-trait(name)`` -  Adds the given trait to the node.
* ``remove-trait(name)`` - Removes the given trait from the node.
* ``set-plugin-data(path, value)`` - Set a value in the plugin data.
* ``extend-plugin-data(path, value, *, unique=False)`` - Treat a value in the
  plugin data as a list, append to it. If unique is True, do not append if the
  item exists.
* ``unset-plugin-data(path)`` - Unset a value in the plugin data.
* ``set-port-attribute(port_id, path, value)`` - Set value on the port
  identified by a MAC or a UUID.
* ``extend-port-attribute(port_id, path, value, *, unique=False)`` - Treat the
  given path on the port as a list, append to it.
* ``del-port-attribute(port_id, path)`` - Unset value on the port identified
  by a MAC or a UUID.
* ``api-call(url, *, headers=None, proxies=None, timeout=5, retries=3, backoff_factor=0.3)``
  - Performs an HTTP GET against the supplied URL.

Loops
-----

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
----------------------

.. code-block:: yaml

    actions:
      - op: "set-attribute"
        args:
          path: "/driver_info/ipmi_address"
          value: "{data[inventory][bmc_address]}"

On a rule execution, values enclosed with braces, usually ``value``, ``msg``,
``address``, and ``subnet`` fields in both actions and conditions, will be
treated as replacement fields and formatted to a string using
`python string formatting notation <https://docs.python.org/3/library/string.html#formatspec>`_.

If the value of any of these keys is a dict or list, strings nested at any
level within the structure will be recursively formatted as well:

.. code-block:: yaml

    actions:
      - op: "set-attribute"
        args:
          path: "/properties/root_device"
          value: '{"serial": "{data[root_device][serial]}"}'

