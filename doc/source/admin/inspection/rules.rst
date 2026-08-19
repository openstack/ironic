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

Full Example
------------

A complete rule showing all available top-level fields:

.. code-block:: yaml

    - uuid: "rule-dell-bmc-setup"
      description: "Configure iDRAC driver for auto-discovered Dell servers"
      priority: 100
      sensitive: true
      phase: main
      conditions:
        - op: contains
          args:
            value: "{inventory[system_vendor][manufacturer]}"
            regex: "(?i)dell"
        - op: is-true
          args:
            value: "{plugin_data[auto_discovered]}"
      actions:
        - op: set-attribute
          args:
            path: "/driver"
            value: "idrac"
        - op: set-attribute
          args:
            path: "/driver_info/redfish_address"
            value: "https://{inventory[bmc_address]}"
        - op: set-attribute
          args:
            path: "/driver_info/redfish_username"
            value: "root"
        - op: log
          args:
            msg: "Configured iDRAC driver for Dell server {node.name}"
            level: info

Rule fields
-----------

* ``uuid`` - Optional unique identifier for the rule. If omitted, one is
  generated automatically.
* ``description`` - Human-readable description of the rule's purpose.
* ``priority`` - Integer controlling the order in which rules are evaluated.
  Higher values run first.
* ``sensitive`` - When ``true``, the rule and its actions are masked in logs
  to protect credentials or other sensitive data. Defaults to ``false``.
* ``phase`` - The inspection phase in which the rule runs. Currently ``main``
  is the only supported phase.
* ``conditions`` - List of conditions that must all evaluate to ``true`` for
  the actions to run. When omitted, the actions always run.
* ``actions`` - List of actions to execute when all conditions are met.

Actions & Conditions
--------------------

Conditions and actions share the same structure. Each is a mapping with:

* ``op`` - the name of the operation: a boolean check (for conditions) or an
  action (for actions), for example ``contains`` or ``set-attribute``.
* ``args`` - a dictionary of arguments for the operation, keyed by argument
  name (the equivalent of Python keyword arguments).

  .. deprecated:: 2026.2
     Passing ``args`` as a list (in the sense of Python ``*args``) is
     deprecated and will be removed in a future release. Use the dictionary
     (named-argument) form instead. The dictionary form is unambiguous and
     avoids surprises with operators such as ``eq`` whose ``values`` argument
     is itself a list.

Each operation below lists the argument names it accepts; provide them as keys
under ``args``. Arguments marked *optional* may be omitted, in which case the
documented default is used.

For example, the ``contains`` condition accepts a ``value`` and a ``regex``:

.. code-block:: yaml

    - op: contains
      args:
        value: "{inventory[system_vendor][manufacturer]}"
        regex: "(?i)dell"

When an argument is itself a list, it is still passed under its single
argument name -- do not spread it out. For example, ``eq`` accepts one
argument named ``values`` holding the list of items to compare:

.. code-block:: yaml

    - op: eq
      args:
        values: ["{node.driver}", "idrac"]

And ``log`` accepts a required ``msg`` and an optional ``level``:

.. code-block:: yaml

    - op: log
      args:
        msg: "Matched node {node.name}"
        level: warning

Conditions
~~~~~~~~~~

Available conditions include:

* ``eq`` - Check that all the given values are equal.

  * ``values`` (list) -- the values to compare.
  * ``force_strings`` (optional, default ``false``) -- convert every value to
    a string before comparing.

* ``lt`` - Check that the values are in strictly ascending order (each value
  is less than the following one).

  * ``values`` (list) -- the values to compare.
  * ``force_strings`` (optional, default ``false``) -- convert every value to
    a string before comparing.

* ``gt`` - Check that the values are in strictly descending order (each value
  is greater than the following one).

  * ``values`` (list) -- the values to compare.
  * ``force_strings`` (optional, default ``false``) -- convert every value to
    a string before comparing.

* ``is-empty`` - Check that ``value`` is ``None`` or an empty string, list or
  dictionary.

  * ``value`` -- the value to test.

* ``in-net`` - Check that ``address`` falls within ``subnet``.

  * ``address`` -- the IP address to test.
  * ``subnet`` -- the network (CIDR) to test against.

* ``matches`` - Check that ``value`` *fully* matches the regular expression
  ``regex``.

  * ``value`` -- the string to test.
  * ``regex`` -- the regular expression.

* ``contains`` - Check that ``value`` contains a match for the regular
  expression ``regex``.

  * ``value`` -- the string to test.
  * ``regex`` -- the regular expression.

* ``one-of`` - Check that ``value`` is one of the entries in ``values``.
  Similar to ``contains``, but also works for non-string values.

  * ``value`` -- the value to look for.
  * ``values`` (list) -- the list of allowed values.

* ``is-none`` - Check that ``value`` is ``None``.

  * ``value`` -- the value to test.

* ``is-true`` - Check that ``value`` is truthy: a boolean ``true``, a non-zero
  number, or the strings ``"yes"`` or ``"true"``.

  * ``value`` -- the value to test.

* ``is-false`` - Check that ``value`` is falsy: a boolean ``false``, zero,
  ``None``, or the strings ``"no"`` or ``"false"``.

  * ``value`` -- the value to test.

To check for the inverse of any of these conditions, prefix the operator with
an exclamation mark (with an optional space) before the op, for example
``!eq`` (not equal) or ``!contains``.

Actions
~~~~~~~

Available actions include:

* ``fail`` - Abort inspection with the given message.

  * ``msg`` -- the failure message.

* ``log`` - Write a message to the Ironic logs.

  * ``msg`` -- the message to log.
  * ``level`` (optional, default ``"info"``) -- the log level, one of
    ``debug``, ``info``, ``warning`` or ``error``.

* ``set-attribute`` - Set a node attribute at ``path`` to ``value``.

  * ``path`` -- the attribute path, in the sense of a JSON patch.
  * ``value`` -- the value to set.

* ``extend-attribute`` - Treat the node attribute at ``path`` as a list and
  append ``value`` to it.

  * ``path`` -- the attribute path.
  * ``value`` -- the value to append.
  * ``unique`` (optional, default ``false``) -- if ``true``, do not append
    when the value is already present.

* ``del-attribute`` - Unset the node attribute at ``path``. Fails on invalid
  node attributes, but does not fail on missing sub-dictionary fields.

  * ``path`` -- the attribute path.

* ``set-capability`` - Set node capability ``name`` to ``value``.

  * ``name`` -- the capability name.
  * ``value`` -- the capability value.

* ``unset-capability`` - Remove a node capability.

  * ``name`` -- the capability name.

* ``add-trait`` - Add a trait to the node.

  * ``name`` -- the trait name.

* ``remove-trait`` - Remove a trait from the node.

  * ``name`` -- the trait name.

* ``set-plugin-data`` - Set a value in the plugin data.

  * ``path`` -- the plugin-data path.
  * ``value`` -- the value to set.

* ``extend-plugin-data`` - Treat a value in the plugin data at ``path`` as a
  list and append ``value`` to it.

  * ``path`` -- the plugin-data path.
  * ``value`` -- the value to append.
  * ``unique`` (optional, default ``false``) -- if ``true``, do not append
    when the value is already present.

* ``unset-plugin-data`` - Unset a value in the plugin data.

  * ``path`` -- the plugin-data path.

* ``set-port-attribute`` - Set an attribute on a port.

  * ``port_id`` -- the port, identified by MAC address or UUID.
  * ``path`` -- the attribute path.
  * ``value`` -- the value to set.

* ``extend-port-attribute`` - Treat the port attribute at ``path`` as a list
  and append ``value`` to it.

  * ``port_id`` -- the port, identified by MAC address or UUID.
  * ``path`` -- the attribute path.
  * ``value`` -- the value to append.
  * ``unique`` (optional, default ``false``) -- if ``true``, do not append
    when the value is already present.

* ``del-port-attribute`` - Unset an attribute on a port.

  * ``port_id`` -- the port, identified by MAC address or UUID.
  * ``path`` -- the attribute path.

* ``api-call`` - Perform an HTTP GET against the supplied URL.

  * ``url`` -- the endpoint to call.
  * ``headers`` (optional) -- a dictionary of request headers.
  * ``proxies`` (optional) -- a dictionary of proxies to use.
  * ``timeout`` (optional, default ``5``) -- request timeout in seconds.
  * ``retries`` (optional, default ``3``) -- number of retries on failure.
  * ``backoff_factor`` (optional, default ``0.3``) -- delay factor between
    retry attempts.

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
      args:
        values: ["{inventory[system_vendor][product_name]}", "{item}"]
      loop: ["HPE ProLiant DL380 Gen10", "PowerEdge R640", "Cisco UCS"]
      multiple: any

Whereas in actions, each iteration of the loop executes same action with the
current item value.

Example of setting multiple attributes using loop:

.. code-block:: yaml

    - op: set-attribute
      args:
        path: "{item[path]}"
        value: "{item[value]}"
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
          value: "{inventory[bmc_address]}"

On a rule execution, values enclosed with braces, usually ``value``, ``msg``,
``address``, and ``subnet`` fields in both actions and conditions, will be
treated as replacement fields and formatted to a string using
`python string formatting notation <https://docs.python.org/3/library/string.html#formatspec>`_.

The following variables are available inside replacement fields:

* ``node`` - the node being inspected. It is a Python **object**, so its
  fields are referenced with **dot** notation, e.g. ``{node.driver}`` or
  ``{node.name}``.
* ``inventory`` - the hardware inventory. It is a **dictionary**, so its
  contents are referenced with **bracket** notation, e.g.
  ``{inventory[system_vendor][product_name]}`` or ``{inventory[bmc_address]}``.
* ``plugin_data`` - data produced by inspection plugins. It is also a
  **dictionary**, referenced with brackets, e.g.
  ``{plugin_data[auto_discovered]}``.
* ``item`` - the current loop item, available only when the condition or
  action defines a ``loop`` (see `Loops`_).

.. note::
   Because ``node`` is an object while ``inventory`` and ``plugin_data`` are
   dictionaries, the access style differs: use ``{node.driver}`` (dot) but
   ``{inventory[bmc_address]}`` (brackets). Mixing them up, for example
   ``{inventory.bmc_address}`` or ``{node[driver]}``, will fail to interpolate
   and the literal, unformatted string will be used instead.

If the value of any of these keys is a dict or list, strings nested at any
level within the structure will be recursively formatted as well:

.. code-block:: yaml

    actions:
      - op: "set-attribute"
        args:
          path: "/properties/capabilities"
          value:
            cpu_arch: "{inventory[cpu][architecture]}"
            bmc_address: "{inventory[bmc_address]}"

