.. -*- rst -*-

=======
Utility
=======

This section describes two API endpoints used by the ``ironic-python-agent``
ramdisk as it communicates with the Bare Metal service.  These were previously
exposed as vendor passthrough methods, however, as ironic-python-agent has
become the standard ramdisk agent, these methods have been made a part of the
official REST API.

.. note::
    **Operators are reminded not to expose the Bare Metal Service's API to
    unsecured networks.** Both API endpoints listed below are available to
    *unauthenticated* clients because the default method for booting the
    ``ironic-python-agent`` ramdisk does not provide the agent with keystone
    credentials.

.. note::
    It is possible to include keys in your ramdisk, or pass keys in via the
    boot method, if your driver supports it; if that is done, you may configure
    these endpoints to require authentication by changing the policy rules
    ``baremetal:driver:ipa_lookup`` and ``baremetal:node:ipa_heartbeat``.
    In light of that, operators are recommended to ensure that this endpoint is
    only available on the ``provisioning`` and ``cleaning`` networks.


Agent Lookup
============

.. rest_method:: GET /v1/lookup

.. versionadded:: 1.22

A ``/lookup`` method is exposed at the root of the REST API. This should only
be used by the ``ironic-python-agent`` ramdisk to retrieve required
configuration data from the Bare Metal service.

By default, ``/v1/lookup`` will only match Nodes that are expected to be
running the ``ironic-python-agent`` ramdisk (for instance, because the Bare
Metal service has just initiated a deployment). It can not be used as a
generic search mechanism, though this behaviour may be changed by setting
the ``[api] restrict_lookup = false`` configuration option for the ironic-api
service.

The query string should include either or both a ``node_uuid`` or an
``addresses`` query parameter. If a matching Node is found, information about
that Node shall be returned.

Normal response codes: 200

Error response codes: 400 404

Request
-------

.. rest_parameters:: parameters.yaml

    - node_uuid: r_node_uuid
    - addresses: r_addresses

Response
--------

Returns only the information about the corresponding Node that the
``ironic-python-agent`` process requires.

.. rest_parameters:: parameters.yaml

    - node: agent_node
    - config: agent_config

Response Example
----------------

.. literalinclude:: samples/lookup-node-response.json
   :language: javascript


Agent Heartbeat
===============

.. rest_method:: POST /v1/heartbeat/{node_ident}

.. versionadded:: 1.22

A ``/heartbeat`` method is exposed at the root of the REST API. This is used
as a callback from within the ``ironic-python-agent`` ramdisk, so that an
active ramdisk may periodically contact the Bare Metal service and provide
the current URL at which to contact the agent.

Normal response codes: 202

Error response codes: 400 404

.. versionadded:: 1.36 ``agent_version`` parameter for passing the version of
  the Ironic Python Agent to Ironic during heartbeat

.. versionadded:: 1.62 ``agent_token`` parameter for passing the token of
  the Ironic Python Agent to Ironic during heartbeat

Request
-------

.. rest_parameters:: parameters.yaml

    - node_ident: node_ident
    - callback_url: callback_url
    - agent_version: agent_version
    - agent_token: agent_token
