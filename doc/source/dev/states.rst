.. _states:

======================
Ironic's State Machine
======================

State Machine Diagram
=====================

The diagram below shows the provisioning states that an Ironic node goes
through during the lifetime of a node. The diagram also depicts the events
that transition the node to different states.

.. figure:: ../images/states.svg
   :width: 660px
   :align: left
   :alt: Ironic state transitions

.. note::

    For more information about the states, see the specification located at
    `ironic-state-machine`_.

.. _ironic-state-machine: http://specs.openstack.org/openstack/ironic-specs/specs/kilo/new-ironic-state-machine.html
