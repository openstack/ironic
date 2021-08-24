.. -*- rst -*-

=======================
Node Management (nodes)
=======================

Nodes can be managed through several sub-resources.

Maintenance mode can be set by the operator, with an optional "reason" stored
by Ironic.

The supplied ``driver_info`` can be validated to ensure that the selected
``driver`` has all the information it requires to manage the Node.

A Node can be rebooted, turned on, or turned off by requesting a change to its
power state. This is handled asynchronously and tracked in the ``target_power_state``
field after the request is received.

A Node's boot device can be changed, and the set of supported boot devices
can be queried.

A request to change a Node's provision state is also tracked asynchronously;
the ``target_provision_state`` represents the requested state. A Node
may transition through several discrete ``provision_state`` steps before arriving
at the requested state. This can vary between drivers and based on configuration.

For example, a Node in the ``available`` state can have an instance deployed to it
by requesting the provision state of ``active``. During this transition, the Node's
``provision_state`` will temporarily be set to ``deploying``, and depending on the driver,
it may also be ``wait call-back``. When the transitions are complete, ``target_provision_state``
will be set to ``None`` and ``provision_state`` will be set to ``active``.
To destroy the instance, request the provision state of ``delete``. During this
transition, the Node may or may not go through a ``cleaning`` state,
depending on the service configuration.


Validate Node
===============

.. rest_method:: GET /v1/nodes/{node_ident}/validate

Request that Ironic validate whether the Node's ``driver`` has enough information
to manage the Node. This polls each ``interface`` on the driver, and returns
the status of that ``interface`` as an element in the response. Note that each
``driver`` may require different information to be supplied, and not all drivers
support all interfaces.

Normal response codes: 200

.. TODO: add error codes

Request
-------

.. rest_parameters:: parameters.yaml

   - node_ident: node_ident

Response
--------

Each element in the response will contain a "result" variable, which will have
a value of "true" or "false", indicating that the interface either has or does
not have sufficient information to function. A value of ``null`` indicates that
the Node's driver does not support that interface.

.. rest_parameters:: parameters.yaml

  - bios: v_bios
  - boot: v_boot
  - console: v_console
  - deploy: v_deploy
  - inspect: v_inspect
  - management: v_management
  - network: v_network
  - power: v_power
  - raid: v_raid
  - rescue: v_rescue
  - storage: v_storage

**Example node validation response:**

.. literalinclude:: samples/node-validate-response.json
   :language: javascript


Set Maintenance Flag
=============================

.. rest_method:: PUT /v1/nodes/{node_ident}/maintenance

Request that Ironic set the maintenance flag on the Node. This will disable
certain automatic actions that the Node's driver may take, and remove
the Node from Nova's available resource pool.

Normal response code: 202

.. TODO: Add link to user / operator documentation on the Maintenance flag

Request
-------

.. rest_parameters:: parameters.yaml

    - node_ident: node_ident
    - reason: reason

**Example request: mark a node for maintenance:**

.. literalinclude:: samples/node-maintenance-request.json

Clear Maintenance Flag
==============================

.. rest_method:: DELETE /v1/nodes/{node_ident}/maintenance

The maintenance flag is unset by sending a DELETE request to this endpoint.
If the request is accepted, Ironic will also clear the ``maintenance_reason``
field.

Normal response code: 202

.. TODO: Add link to user / operator documentation on the Maintenance flag

Request
-------

.. rest_parameters:: parameters.yaml

    - node_ident: node_ident

Set Boot Device
===============

.. rest_method:: PUT /v1/nodes/{node_ident}/management/boot_device

Set the boot device for the given Node, and set it persistently or for one-time
boot. The exact behaviour of this depends on the hardware driver.

.. note:: In some drivers, eg.  the ``*_ipmitool`` family, this method initiates a synchronous call
          to the hardware management device (BMC). It should be used with caution! This
          is `a known bug <https://bugs.launchpad.net/ironic/+bug/1427923>`_.

.. note:: Some drivers do not support one-time boot, and always set the boot device
          persistently.

Normal response code: 204

.. TODO: add error codes

Request
-------

.. rest_parameters:: parameters.yaml

    - node_ident: node_ident
    - boot_device: req_boot_device
    - persistent: req_persistent

**Example JSON request body to set boot device:**

.. literalinclude:: samples/node-set-boot-device.json


Get Boot Device
===============

.. rest_method:: GET /v1/nodes/{node_ident}/management/boot_device

Get the current boot device for the given Node.

.. note:: In some drivers, eg. the ``*_ipmitool`` family, this method initiates a synchronous call
          to the hardware management device (BMC). It should be used with caution! This
          is `a known bug <https://bugs.launchpad.net/ironic/+bug/1427923>`_.

Normal response code: 200

.. TODO: add error codes

Request
-------

.. rest_parameters:: parameters.yaml

    - node_ident: node_ident

Response
--------

.. rest_parameters:: parameters.yaml

    - boot_device: boot_device
    - persistent: persistent

**Example JSON response to get boot device:**

.. literalinclude:: samples/node-get-boot-device-response.json


Get Supported Boot Devices
===========================

.. rest_method:: GET /v1/nodes/{node_ident}/management/boot_device/supported

Retrieve the acceptable set of supported boot devices for a specific Node.

Normal response code: 200

.. TODO: add error codes

Request
-------

.. rest_parameters:: parameters.yaml

    - node_ident: node_ident

Response
--------

.. rest_parameters:: parameters.yaml

    - supported_boot_devices: supported_boot_devices

**Example response listing supported boot devices:**

.. literalinclude:: samples/node-get-supported-boot-devices-response.json


Inject NMI (Non-Masking Interrupts)
===================================

.. rest_method:: PUT /v1/nodes/{node_ident}/management/inject_nmi

.. versionadded:: 1.29

Inject NMI (Non-Masking Interrupts) for the given Node. This feature
can be used for hardware diagnostics, and actual support depends on a
driver.

Normal response code: 204 (No content)

Error codes:
    - 400 (Invalid)
    - 403 (Forbidden)
    - 404 (NotFound)
    - 406 (NotAcceptable)
    - 409 (NodeLocked, ClientError)

Request
-------

.. rest_parameters:: parameters.yaml

    - node_ident: node_ident

**Request to inject NMI to a node has to be empty dictionary:**

.. literalinclude:: samples/node-inject-nmi.json


Node State Summary
==================

.. rest_method:: GET /v1/nodes/{node_ident}/states

Get a summary of the Node's current power, provision, boot mode, raid, and console status.

.. versionadded:: 1.75
   Introduced ``boot_mode`` and ``secure_boot`` fields.

Normal response code: 200

Request
-------

.. rest_parameters:: parameters.yaml

    - node_ident: node_ident

Response
--------

.. rest_parameters:: parameters.yaml

    - power_state: power_state
    - target_power_state: target_power_state
    - provision_state: provision_state
    - target_provision_state: target_provision_state
    - provision_updated_at: provision_updated_at
    - last_error: last_error
    - console_enabled: console_enabled
    - raid_config: raid_config
    - target_raid_config: target_raid_config
    - boot_mode: boot_mode
    - secure_boot: secure_boot

**Example node state:**

.. literalinclude:: samples/node-get-state-response.json

Change Node Boot Mode
=====================

.. rest_method:: PUT /v1/nodes/{node_ident}/states/boot_mode

Request a change to the Node's boot mode.

.. versionadded:: 1.76
   A change in node's boot mode can be requested.

Normal response code: 202 (Accepted)

Error codes:
    - 409 (Conflict, NodeLocked, ClientError)
    - 400 (Invalid, InvalidStateRequested, InvalidParameterValue)
    - 404 (NotFound)
    - 503 (NoFreeConductorWorkers)

Request
-------

.. rest_parameters:: parameters.yaml

    - node_ident: node_ident
    - target: req_target_boot_mode

**Example request for UEFI boot:**

.. literalinclude:: samples/node-set-boot-mode-uefi.json

**Example request for Legacy BIOS boot:**

.. literalinclude:: samples/node-set-boot-mode-bios.json


Change Node Secure Boot
=======================

.. rest_method:: PUT /v1/nodes/{node_ident}/states/secure_boot

Request a change to the Node's secure boot state.

.. versionadded:: 1.76
   A change in node's secure boot state can be requested.

Normal response code: 202 (Accepted)

Error codes:
    - 409 (Conflict, NodeLocked, ClientError)
    - 400 (Invalid, InvalidStateRequested, InvalidParameterValue)
    - 404 (NotFound)
    - 503 (NoFreeConductorWorkers)

Request
-------

.. rest_parameters:: parameters.yaml

    - node_ident: node_ident
    - target: req_target_secure_boot

**Example request to turn off secure boot:**

.. literalinclude:: samples/node-set-secure-boot-off.json

**Example request to turn on secure boot:**

.. literalinclude:: samples/node-set-secure-boot-on.json


Change Node Power State
=======================

.. rest_method:: PUT /v1/nodes/{node_ident}/states/power

Request a change to the Node's power state.

Normal response code: 202 (Accepted)

.. versionadded:: 1.27
   In the request, the ``target`` value can also be one of ``soft power off``
   or ``soft rebooting``.

.. versionadded:: 1.27
   In the request, a ``timeout`` can be specified.

Error codes:
    - 409 (NodeLocked, ClientError)
    - 400 (Invalid, InvalidStateRequested, InvalidParameterValue)
    - 406 (NotAcceptable)
    - 503 (NoFreeConductorWorkers)

Request
-------

.. rest_parameters:: parameters.yaml

    - node_ident: node_ident
    - target: req_target_power_state
    - timeout: power_timeout

**Example request to power off a Node:**

.. literalinclude:: samples/node-set-power-off.json

**Example request to soft power off a Node with timeout:**

.. literalinclude:: samples/node-set-soft-power-off.json


Change Node Provision State
===========================

.. rest_method:: PUT /v1/nodes/{node_ident}/states/provision

Request a change to the Node's provision state.

Acceptable target states depend on the Node's current provision state. More
detailed documentation of the Ironic State Machine is available
`in the developer docs <https://docs.openstack.org/ironic/latest/contributor/states.html>`_.

.. versionadded:: 1.35
   A ``configdrive`` can be provided when setting the node's provision target state to ``rebuild``.

.. versionadded:: 1.38
  A node can be rescued or unrescued by setting the node's provision target state to
  ``rescue`` or ``unrescue`` respectively.

.. versionadded:: 1.56
   A ``configdrive`` can be a JSON object with ``meta_data``, ``network_data``
   and ``user_data``.

.. versionadded:: 1.59
   A ``configdrive`` now accepts ``vendor_data``.

.. versionadded:: 1.69
   ``deploy_steps`` can be provided when settings the node's provision target
   state to ``active`` or ``rebuild``.

.. versionadded:: 1.70
   ``disable_ramdisk`` can be provided to avoid booting the ramdisk during
   manual cleaning.

Normal response code: 202

Error codes:
    - 409 (NodeLocked, ClientError)
    - 400 (InvalidState, NodeInMaintenance)
    - 406 (NotAcceptable)
    - 503 (NoFreeConductorWorkers)

Request
-------

.. rest_parameters:: parameters.yaml

    - node_ident: node_ident
    - target: req_provision_state
    - configdrive: configdrive
    - clean_steps: clean_steps
    - deploy_steps: deploy_steps
    - rescue_password: rescue_password
    - disable_ramdisk: disable_ramdisk

**Example request to deploy a Node, using a configdrive served via local webserver:**

.. literalinclude:: samples/node-set-active-state.json

**Example request to deploy a Node with custom deploy step:**

.. literalinclude:: samples/node-set-active-state-deploy-steps.json

**Example request to clean a Node, with custom clean step:**

.. literalinclude:: samples/node-set-clean-state.json


Set RAID Config
===============

.. rest_method:: PUT /v1/nodes/{node_ident}/states/raid

.. versionadded:: 1.12

Store the supplied configuration on the Node's ``target_raid_config`` property.
This property must be structured JSON, and will be validated by the driver upon receipt. The request
schema is defined in the `documentation for the RAID feature <https://docs.openstack.org/ironic/latest/admin/raid.html>`_

.. note:: Calling this API only stores the requested configuration; it will be applied the next time
  that the Node transitions through the ``cleaning`` phase.

Normal response code: 204

.. TODO: add more description, response code, sample response

Request
-------

.. rest_parameters:: parameters.yaml

    - node_ident: node_ident
    - target_raid_config: req_target_raid_config

**Example requested RAID config:**

.. literalinclude:: samples/node-set-raid-request.json

.. TODO: add more description, response code, sample response

Get Console
===========

.. rest_method:: GET /v1/nodes/{node_ident}/states/console

Get connection information about the console.

.. TODO: add more description, response code, sample response

Request
-------

.. rest_parameters:: parameters.yaml

    - node_ident: node_ident

.. TODO: add more description, response code, sample response

Start/Stop Console
===================

.. rest_method:: PUT /v1/nodes/{node_ident}/states/console

Start or stop the serial console.

.. TODO: add more description, response code, sample response

Request
-------

.. rest_parameters:: parameters.yaml

    - node_ident: node_ident
    - enabled: req_console_enabled
