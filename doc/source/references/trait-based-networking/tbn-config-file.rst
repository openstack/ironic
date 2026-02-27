===================================================
Trait Based Networking Configuration File Reference
===================================================

Introduction
------------

Trait Based Networking's trait configuration file is a YAML format file which
defines a set of traits, and their corresponding actions. This file is
ingested and validated by the Ironic conductor at start-up.

Trait Layout
------------

Below is a valid YAML example trait:

.. code-block:: yaml

    CUSTOM_TRAIT_NAME:
      order: 1
      actions:
        - action: bond_ports
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
    Refer to
    :doc:`/references/trait-based-networking/filter-expression-reference` for
    detailed explanations on how to write valid filter expressions.

and the following optional keys:

* ``max_count`` - The maximum number of objects that can match this action.
  There is no default maximum.
* ``min_count`` - The minimum number of objects that *must* match before this
  action applies. The default minimum is effectively 1.

Available Actions
-----------------

The following actions are currently available:

* ``attach_port`` - Attach (port, network) pairs that pass this action's
  filter expression.
* ``attach_portgroup`` - Attach (portgroup, network) pairs that pass this
  action's filter expression.

Future actions are planned. This document will be updated as they become
available.

Example Configuration File
--------------------------

An example Trait Based Networking configuration file is shipped with Ironic.
A copy is `available here <https://opendev.org/openstack/ironic/src/branch/master/etc/ironic/trait_based_networks.yaml.sample>`_.
While backwards compatibility breaking changes are generally avoided where
possible, please be aware that the linked copy may not be compatible with your
version of Ironic.
