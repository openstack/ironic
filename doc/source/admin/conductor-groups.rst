.. _conductor-groups:

================
Conductor Groups
================

Overview
========

Large scale operators tend to have needs that involve creating
well defined and delinated resources. In some cases, these systems
may reside close by or in far away locations. Reasoning may be simple
or complex, and yet is only known to the deployer and operator of the
infrastructure.

A common case is the need for delineated high availability domains
where it would be much more efficient to manage a datacenter in Antarctica
with a conductor in Antarctica, as opposed to a conductor in New York City.

How it works
============

Starting in ironic 11.1, each node has a ``conductor_group`` field which
influences how the ironic conductor calculates (and thus allocates)
baremetal nodes under ironic's management. This calculation is performed
independently by each operating conductor and as such if a conductor has
a ``[conductor]conductor_group`` configuration option defined in its
`ironic.conf` configuration file, the conductor will then be limited to
only managing nodes with a matching ``conductor_group`` string.

.. note::
   Any conductor without a ``[conductor]conductor_group`` setting will
   only manage baremetal nodes without a ``conductor_group`` value set upon
   node creation. If no such conductor is present when conductor groups are
   configured, node creation will fail unless a ``conductor_group`` is
   specified upon node creation.

.. warning::
   Nodes without a ``conductor_group`` setting can only be managed when a
   conductor exists that does not have a ``[conductor]conductor_group``
   defined. If all conductors have been migrated to use a conductor group,
   such nodes are effectively "orphaned".

How to use
==========

A conductor group value may be any case insensitive string up to 255
characters long which matches the ``^[a-zA-Z0-9_\-\.]*$`` regular
expression.

#. Set the ``[conductor]conductor_group`` option in ironic.conf
   on one or more, but not all conductors::

    [conductor]
    conductor_group = OperatorDefinedString

#. Restart the ironic-conductor service.

#. Set the conductor group on one or more nodes::

    baremetal node set \
        --conductor-group "OperatorDefinedString" <uuid>

#. As desired and as needed, remaining conductors can be updated with
   the first two steps. Please be mindful of the constraints covered
   earlier in the document related to ability to manage nodes.
