======================
Trait Based Networking
======================

Introduction
------------

Trait Based Networking, or TBN for short, is an Ironic feature that allows an
Openstack installation utilizing Ironic, Neutron, and Nova to dynamically
configure port scheduling for Ironic nodes.

Configure
---------

To configure and enable TBN for your Ironic installation please see
:doc:`/install/configure-trait-based-networking`
variable_name: /[a-z]+\.[a-z\_]+/

Available Actions
-----------------

Attach port - Attach one or more ports belonging to a node to a network
              (aka vif)
Attach portgroup - Attach one or more portgroups belonging to a node to a
                   network (aka vif)

Future actions are coming.

Filter Expression Primer
------------------------

Filter Expressions are how network related objects are filtered or matched with
their applicable traits.

Let's look at a basic filter expression:

  .. code-block:: console

     port.vendor == "purple"

This expression consists of three parts:

#. A named variable: ``port.vendor`` - This means the expression will consider
   a port's vendor field.
#. A comparator: ``==`` - In this case equality.
#. A string literal: ``"purple"`` - Gives a comparison value to compare against
   the contents of the named variable.

Taken together this expression can be read in plain English as:
'filter for ports with vendor that is exactly equal to the string "purple"'.

All available variables and comparators are listed in the
:doc:`/references/trait-based-networking/filter-expression-reference`.

Single expressions can be linked together using boolean operators:

- "&&" boolean AND

- "||" boolean OR

Like so:

  .. code-block:: console

     port.vendor == "purple" && port.category != "privatenet"

Again in plain English this could be read as: 'filter for ports with vendor
that is exactly equal to the string "purple" and whose category field is not
"privatenet"'.

Functions
~~~~~~~~~

There's also a couple of functions available to filter ports vs portgroups:

- ``port.is_port`` will return true if the port is a port, and false otherwise.
- ``port.is_portgroup`` will return true if the port is a portgroup, and false
  otherwise.

Function expressions can be used in isolation:

  .. code-block:: console

     port.is_port

Or linked with other expressions:

  .. code-block:: console

     port.is_port && port.vendor == "green"
