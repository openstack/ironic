Node auto-discovery
===================

The Bare Metal service is capable of automatically enrolling new nodes that
somehow (through external means, e.g. :ref:`configure-unmanaged-inspection`)
boot into an IPA ramdisk and call back with inspection data. This feature must
be enabled explicitly in the configuration:

.. code-block:: ini

   [DEFAULT]
   default_inspect_interface = agent

   [auto_discovery]
   enabled = True
   driver = ipmi

The newly created nodes will appear in the ``enroll`` provision state with the
``driver`` field set to the value specified in the configuration, as well as a
boolean ``auto_discovered`` flag in the :ref:`plugin-data`.

After the node is enrolled, it will automatically go through the normal
inspection process, which includes, among other things, creating ports.
Any errors during this process will be reflected in the node's ``last_error``
field (the node will not be deleted).

.. TODO(dtantsur): inspection rules examples once ready

Limitations
-----------

* Setting BMC credentials is a manual task. The Bare Metal service does not
  generate new credentials for you even on those machines where it's possible
  through ``ipmitool``.

* Node uniqueness is checked using the supplied MAC addresses. In rare cases,
  it is possible to create duplicate nodes.

* Enabling discovery allows anyone with API access to create nodes with given
  MAC addresses and store inspection data of arbitrary size for them. This can
  be used for denial-of-service attacks.

* Setting ``default_inspect_interface`` is required for the inspection flow
  to continue correctly after the node creation.
