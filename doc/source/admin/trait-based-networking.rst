======================
Trait Based Networking
======================

Introduction
------------

Trait Based Networking, or TBN for short, is an Ironic feature that allows an
Openstack installation utilizing Ironic, Neutron, and Nova to dynamically
configure port scheduling for Ironic nodes.

Enable and Configure
--------------------

To configure and enable TBN for your Ironic installation please see
:doc:`/install/configure-trait-based-networking`

Terminology
-----------

First some terms:

- Node: An Ironic node.
- Trait: A set of actions referred to by a name.
- Action or Trait Action: A defined operation to apply to a node if
  the action's Filter Expression matches network objects associated
  with a node.
- Filter Expression: A boolean expression which filters for specific network
  objects like a port, portgroup or network.
- Port: A network interface.
- Portgroup: A set of ports, grouped together.
- Dynamic Portgroup: An ephemeral portgroup that is created by a trait's action
  and is subsequently destroyed once detached.
- Network (aka VIF): A neutron network.


Trait Actions
-------------

The core of TBN functionality lies in actions that each trait defines. Each
action allows the operator to define how exactly TBN will setup networking for
the node.

The following actions are available:

- Attach port: Attach one or more ports belonging to a node to a network
  (aka vif).
- Attach portgroup: Attach one or more portgroups belonging to a node to a
  network (aka vif).
- Group and attach ports: Create a dynamic portgroup and attach it to a
  network.

In the future more actions may be added.

See :ref:`tbn-config-file` for more information on configuring and applying
trait actions.

.. _tbn-config-file:

Configuration File Reference
----------------------------

Trait Based Networking's trait configuration file is a YAML format file which
defines a set of traits, and their corresponding actions. This file is
ingested and validated by the Ironic conductor at start-up.

Trait Layout
~~~~~~~~~~~~

Below is a valid YAML example trait:

.. code-block:: yaml

    CUSTOM_TRAIT_NAME:
      order: 1
      actions:
        - action: group_and_attach_ports
          filter: port.vendor == 'vendor_string'
          min_count: 2
        - action: attach_port
          filter: port.vendor == 'vendor_string' && port.is_portgroup
          max_count: 1

``CUSTOM_TRAIT_NAME`` is the trait's name.  Each trait is identified by a name
which *must* start with ``CUSTOM``. It's ``order`` is ``1``. Ordering is
ascending, so lower orders will apply first.

``actions`` is a list of actions to apply if this trait matches one defined
in a node's ``instance_info.traits`` field.

Each action has the following necessary keys:

* ``action`` - The action to take.
* ``filter`` - The Filter Expression to apply with this action.

.. note::
    Refer to :ref:`tbn-filter-expression-reference` for detailed explanations
    on how to write valid filter expressions.

and the following optional keys:

* ``max_count`` - The maximum number of objects that can match this action.
  There is no default maximum.
* ``min_count`` - The minimum number of objects that *must* match before this
  action applies. The default minimum is effectively 1.

Available Actions
~~~~~~~~~~~~~~~~~

The following actions are currently available:

* ``attach_port`` - Attach (port, network) pairs that pass this action's
  filter expression.
* ``attach_portgroup`` - Attach (portgroup, network) pairs that pass this
  action's filter expression.
* ``group_and_attach_ports`` - Select a set of ports. Create a dynamic
  portgroup comprised of the set of ports. Then attach the newly created
  dynamic portgroup to a suitable network. This action must set a
  ``min_count`` of at least 2. Also note that all ports selected for the
  portgroup must have the same ``physical_network``.

Future actions are planned. This document will be updated as they become
available.

Example Configuration File
~~~~~~~~~~~~~~~~~~~~~~~~~~

An example Trait Based Networking configuration file is shipped with Ironic.
A copy is `available here <https://opendev.org/openstack/ironic/src/branch/master/etc/ironic/trait_based_networks.yaml.sample>`_.
While backwards compatibility breaking changes are generally avoided where
possible, please be aware that the linked copy may not be compatible with your
version of Ironic.

.. _tbn-filter-expression-reference:

Filter Expression Reference
---------------------------

.. note::

    If this document disagrees with
    ``ironic.common.trait_based_networking.grammar.parser.FILTER_EXPRESSION_GRAMMAR``
    then this document is wrong. `FILTER_EXPRESSION_GRAMMAR`_ is the ultimate
    source of truth regarding the grammar and parsing of TBN filter expressions.

A filter expression is a boolean expression which evaluates to ``True`` if the
objects under consideration match the filter, and ``False`` otherwise.

Filter expressions allow Ironic operators to create custom filtering logic for
traits which will apply specific network actions or operations to nodes.

Filter expressions consider two basic network objects:

1. ``portlike``: (aka ``port`` in this document) which can be either an Ironic
   port or portgroup.
2. ``network``: Essentially a Neutron vif (virtual interface).

A filter expression that evaluates to ``True`` for a given tuple of
``(portlike, network)`` would cause a match to occur for the trait the filter
belongs to. The trait's defined actions would then apply if enough matches
occur to satisfy the action's requirements.

Single Expression
~~~~~~~~~~~~~~~~~

A ``single expression`` has the form of:

.. code-block:: python

   variable_name comparator string_literal

Where ``variable_name`` is one of the available `variables`_, ``comparator``
is one of the available `comparators`_, and ``string_literal`` is a valid
`string literal`_.

A full example of a single expression:

.. code-block:: python

    port.category == 'public'

Which would evaluate to ``True`` whenever a portlike is considered that has a
``category`` that exactly equals ``public``.

Function Expression
~~~~~~~~~~~~~~~~~~~

A ``function expression`` has the form of:

.. code-block:: python

   function

See `Functions`_ for available ``functions``.

Compound Expression
~~~~~~~~~~~~~~~~~~~

A compound expression consists of two expressions joined by a
`comparator`_.

.. code-block:: python

   port.category == 'public' && port.vendor == 'green'

Parenthesis
~~~~~~~~~~~

Parenthesis can be used to group expressions together to guarantee evaluation
precedence. For example:

.. code-block:: python

   port.category == 'private' || (port.vendor == 'purple' && network.name == 'hypernet')

Would cause the right-hand side of ``||`` to be evaluated together before
evaluating the result against the left side of ``||``.

.. _comparator:

Comparators
~~~~~~~~~~~

Comparators allow comparisons between variables and string literals.

========== ======================= ==========================================
Comparator Name                    Explanation
========== ======================= ==========================================
``==``     Equality                Check for exact matches.
``!=``     Inequality              Check for any difference.
``>=``     Greater than or equal   Is the variable greater than or equal to the string literal?
``>``      Greater than            Is the variable greater than the string literal?
``<=``     Less than or equal      Is the variable less than or equal to the string literal?
``<``      Less than               Is the variable less than the string literal?
``=~``     Prefix match            Does the beginning of the variable match the string literal?
========== ======================= ==========================================

Examples
^^^^^^^^

.. code-block:: python

   port.vendor == 'purple'

If a port's ``vendor`` is exactly ``purple`` then this expression will
evaluate to ``True`` and ``False`` otherwise.

.. code-block:: python

   port.category =~ 'green'

If a port's ``category`` starts with the string ``green`` then this expression
will evaluate to ``True`` and ``False`` otherwise.

.. code-block:: python

   network.name != 'private'

Match only networks if their name name is NOT ``private``.

.. _boolean-operator:

Boolean Operators
~~~~~~~~~~~~~~~~~

Used to join expressions to create complex filtering logic.

======== ==== ======================================================
Operator Name Explanation
======== ==== ======================================================
``&&``   And  If both expressions are ``True``, then return ``True``.
``||``   Or   If either expression is ``True``, then return ``True``.
======== ==== ======================================================

Examples
^^^^^^^^

.. code-block:: python

   port.vendor == 'purple' && port.category == 'private'

Will match a port if it's ``vendor`` is ``purple`` and it's category is
``private``.

.. code-block:: python

   port.vendor == 'purple' || port.vendor == 'green'

Will match a port if it's ``vendor`` is ``purple`` or ``green``.

Functions
~~~~~~~~~

Functions allow basic querying of TBN related objects.

================= ===================================================================
Function          Explanation
================= ===================================================================
port.is_port      Returns ``True`` if the portlike under consideration is a ``port``.
port.is_portgroup Returns ``True`` if the portlike under consideration is a ``portgroup``.
================= ===================================================================

Examples
^^^^^^^^

.. code-block:: python

    port.is_port

Will match portlikes which are a ``port``.

String literal
~~~~~~~~~~~~~~

String literals are enclosed by single quotes: ``'``.
String literals only allow alphanumeric characters, underscores, dashes, and
periods.

The following regular expression encompasses valid string literals:
``/\'[A-Za-z0-9_\-\.]*\'/``

Variables
~~~~~~~~~

Variables allow basic querying of network related objects in filter
expressions. Available variables are listed below:

- network.name
- network.tags
- port.address
- port.category
- port.physical_network
- port.vendor

A variable whose value is unset, such as ``port.category`` on a port without
a category, never matches, regardless of comparator. This includes ``!=``, so
``port.category != 'public'`` does not match a port without a category.

.. note::

    ``port.vendor`` only applies to ports. Portgroups have no ``vendor``
    field, so ``port.vendor`` is always unset for a portgroup and never
    matches. Use the ``port.is_portgroup`` or ``port.is_port`` `functions`_
    to handle portgroups explicitly. For example, to match portgroups as well
    as ports from a given vendor:

    .. code-block:: python

        port.is_portgroup || port.vendor == 'purple'

.. _FILTER_EXPRESSION_GRAMMAR: https://opendev.org/openstack/ironic/src/branch/master/ironic/common/trait_based_networking/grammar/parser.py#L17
