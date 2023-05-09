.. -*- rst -*-

=====================
Indicators Management
=====================

The Indicators management is an extension of the node ReST API endpoint that
allows reading and toggling the indicators (e.g. LEDs) on the hardware
units.

List Indicators
===============

.. rest_method:: GET /v1/nodes/{node_ident}/management/indicators

.. versionadded:: 1.63

List all available indicator names for each of the hardware components.
The components that the ``redfish`` driver may have are: ``system``,
``chassis`` and ``drive``. The actual list depends on the support by the
underlying hardware.

Normal response code: 200

Error response codes: 404 (if node not found)

Request
-------

.. rest_parameters:: parameters.yaml

   - node_ident: node_ident

Response Parameters
-------------------

.. rest_parameters:: parameters.yaml

   - components: n_components
   - name: component_name
   - links: links

**Example list of indicators for the node:**

.. literalinclude:: samples/node-indicators-list-response.json
   :language: javascript


Get Indicator State
===================

.. rest_method:: GET /v1/nodes/{node_ident}/management/indicators/{ind_ident}@{component}

.. versionadded:: 1.63

Retrieves the state of a chosen indicator for a given component of the node.
The value of the field in the response object represents its state. The values
can be one of  ``OFF``, ``ON``, ``BLINKING`` or ``UNKNOWN``.

Normal response code: 200

Error response codes: 404 (if node, component or indicator is not found)

Request
-------

.. rest_parameters:: parameters.yaml

  - node_ident: node_ident
  - component: component
  - ind_ident: ind_ident

Response Parameters
-------------------

.. rest_parameters:: parameters.yaml

   - state: n_ind_state

**Example list of indicators for a given component of the node:**

.. literalinclude:: samples/node-indicators-get-state-response.json
  :language: javascript


Set Indicator State
===================

.. rest_method:: PUT /v1/nodes/{node_ident}/management/indicators/{ind_ident}@{component}

.. versionadded:: 1.63

Set the state of the desired indicators of the component.

Normal response code: 204 (No content)

Error codes:
    - 400 (if state is not an accepted value)
    - 404 (if node, component or indicator is not found)

Request
-------

.. rest_parameters:: parameters.yaml

   - node_ident: node_ident
   - component: component
   - ind_ident: ind_ident
   - state: n_ind_state

**Set the State of an Indicator**

.. literalinclude:: samples/node-indicators-set-state.json
