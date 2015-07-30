========================
REST API Version History
========================

**1.27** (Ocata)

    Add ``soft rebooting`` and ``soft power off`` as possible values
    for the ``target`` field of the power state change payload, and
    also add ``timeout`` field to it.

**1.26** (Ocata)

    Add portgroup ``mode`` and ``properties`` fields.

**1.25** (Ocata)

    Add possibility to unset chassis_uuid from a node.

**1.24** (Ocata)

    Added new endpoints '/v1/nodes/<node>/portgroups' and '/v1/portgroups/<portgroup>/ports'.
    Added new field ``port.portgroup_uuid``.

**1.23** (Ocata)

    Added '/v1/portgroups/ endpoint.

**1.22** (Newton, 6.1.0)

    Added endpoints for deployment ramdisks.

**1.21** (Newton, 6.1.0)

    Add node ``resource_class`` field.

**1.20** (Newton, 6.1.0)

    Add node ``network_interface`` field.

**1.19** (Newton, 6.1.0)

    Add ``local_link_connection`` and ``pxe_enabled`` fields to the port object.

**1.18** (Newton, 6.1.0)

    Add ``internal_info`` readonly field to the port object, that will be used
    by ironic to store internal port-related information.

**1.17** (Newton, 6.0.0)

    Addition of provision_state verb ``adopt`` which allows an operator
    to move a node from ``manageable`` state to ``active`` state without
    performing a deployment operation on the node. This is intended for
    nodes that have already been deployed by external means.

**1.16** (Mitaka, 5.0.0)

    Add ability to filter nodes by driver.

**1.15** (Mitaka, 5.0.0)

    Add ability to do manual cleaning when a node is in the manageable
    provision state via PUT v1/nodes/<identifier>/states/provision,
    target:clean, clean_steps:[...].

**1.14** (Liberty, 4.2.0)

    Make the following endpoints discoverable via Ironic API:

    * '/v1/nodes/<UUID or logical name>/states'
    * '/v1/drivers/<driver name>/properties'

**1.13** (Liberty, 4.2.0)

    Add a new verb ``abort`` to the API used to abort nodes in
    ``CLEANWAIT`` state.

**1.12** (Liberty, 4.2.0)

    This API version adds the following abilities:

    * Get/set ``node.target_raid_config`` and to get
      ``node.raid_config``.
    * Retrieve the logical disk properties for the driver.

**1.11** (Liberty, 4.0.0, breaking change)

    Newly registered nodes begin in the ``enroll`` provision state by default,
    instead of ``available``. To get them to the ``available`` state,
    the ``manage`` action must first be run to verify basic hardware control.
    On success the node moves to ``manageable`` provision state. Then the
    ``provide`` action must be run. Automated cleaning of the node is done and
    the node is made ``available``.

**1.10** (Liberty, 4.0.0)

    Logical node names support all RFC 3986 unreserved characters.
    Previously only valid fully qualified domain names could be used.

**1.9** (Liberty, 4.0.0)

    Add ability to filter nodes by provision state.

**1.8** (Liberty, 4.0.0)

    Add ability to return a subset of resource fields.

**1.7** (Liberty, 4.0.0)

    Add node ``clean_step`` field.

**1.6** (Kilo)

    Add :ref:`inspection` process: introduce ``inspecting`` and ``inspectfail``
    provision states, and ``inspect`` action that can be used when a node is in
    ``manageable`` provision state.

**1.5** (Kilo)

    Add logical node names that can be used to address a node in addition to
    the node UUID. Name is expected to be a valid `fully qualified domain
    name`_ in this version of API.

**1.4** (Kilo)

    Add ``manageable`` state and ``manage`` transition, which can be used to
    move a node to ``manageable`` state from ``available``.
    The node cannot be deployed in ``manageable`` state.
    This change is mostly a preparation for future inspection work
    and introduction of ``enroll`` provision state.

**1.3** (Kilo)

    Add node ``driver_internal_info`` field.

**1.2** (Kilo, breaking change)

    Renamed NOSTATE (``None`` in Python, ``null`` in JSON) node state to
    ``available``. This is needed to reduce confusion around ``None`` state,
    especially when future additions to the state machine land.

**1.1** (Kilo)

    This was the initial version when API versioning was introduced.
    Includes the following changes from Kilo release cycle:

    * Add node ``maintenance_reason`` field and an API endpoint to
      set/unset the node maintenance mode.

    * Add sync and async support for vendor passthru methods.

    * Vendor passthru endpoints support different HTTP methods, not only
      ``POST``.

    * Make vendor methods discoverable via the Ironic API.

    * Add logic to store the config drive passed by Nova.

    This has been the minimum supported version since versioning was
    introduced.

**1.0** (Juno)

    This version denotes Juno API and was never explicitly supported, as API
    versioning was not implemented in Juno, and **1.1** became the minimum
    supported version in Kilo.

.. _fully qualified domain name: https://en.wikipedia.org/wiki/Fully_qualified_domain_name

