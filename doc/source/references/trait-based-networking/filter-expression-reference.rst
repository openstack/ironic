Filter Expression Reference
===========================

This reference is for Trait Based Networking's Filter Expressions.

.. note::

    If this document disagrees with
    ``ironic.common.trait_based_networking.grammar.parser.FILTER_EXPRESSION_GRAMMAR``
    then this document is wrong. `FILTER_EXPRESSION_GRAMMAR`_ is the ultimate
    source of truth regarding the grammar and parsing of TBN filter expressions.

Filter Expressions
------------------

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
^^^^^^^^^^^^^^^^^

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
^^^^^^^^^^^^^^^^^^^

A ``function expression`` has the form of:

.. code-block:: python

   function

See `Functions`_ for available ``functions``.


Compound Expression
^^^^^^^^^^^^^^^^^^^

A compound expression consists of two expressions joined by a
`comparator`_.

.. code-block:: python

   port.category == 'public' && port.vendor == 'green'


Parenthesis
^^^^^^^^^^^

Parenthesis can be used to group expressions together to guarantee evaluation
precedence. For example:

.. code-block:: python

   port.category == 'private' || (port.vendor == 'purple' && network.name == 'hypernet')

Would cause the right-hand side of ``||`` to be evaluated together before
evaluating the result against the left side of ``||``.

.. _comparator:

Comparators
-----------

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
-----------------

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
---------

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
--------------

String literals are enclosed by single quotes: ``'``.
String literals only allow alphanumeric characters, underscores, dashes, and
periods.

The following regular expression encompasses valid string literals:
``/\'[A-Za-z0-9_\-\.]*\'/``

Variables
---------

Variables allow basic querying of network related objects in filter
expressions. Available variables are listed below:

- network.name
- network.tags
- port.address
- port.category
- port.physical_network
- port.vendor

.. _FILTER_EXPRESSION_GRAMMAR: https://opendev.org/openstack/ironic/src/branch/master/ironic/common/trait_based_networking/grammar/parser.py#L17
