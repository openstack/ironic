.. _configure-standalone-networking:

============================================
Configure the Standalone Networking Service
============================================

The Standalone Networking service provides network switch management for bare
metal provisioning in environments where Neutron is not available or not
desired. This service manages switch port configurations through a dedicated
``ironic-networking`` process that communicates with the Ironic conductor via
RPC.  The service is capable of provisioning switch port attributes on the
neighboring switches to include VLAN configuration information for both access
and trunk ports.

.. Warning:: The standalone networking feature is experimental and the API may
             change in future releases.  Specifically, using the ``port.extra``
             attribute to pass switchport configuration on each individual
             port will be re-visited and likely converted to use a more formal
             API structure.

.. Note:: The expected starting condition before a node is enrolled is that its
          switch ports are configured onto the "idle" VLAN.  The "idle" VLAN
          can be considered as the default VLAN for a port.  The networking
          service will always set the switch port back to this VLAN whenever no
          specific VLAN is required based on the state of the node.  It is
          expected that this VLAN is routable back to the Ironic API.
          Nodes that are not configured onto the "idle" VLAN will fail the
          initial inspection; therefore, no LLDP information will be available
          to identify which switch ports need to be configured for that node.
          In that case, ``local_link_connection`` information must be provided
          manually for each port.


Overview
========

The standalone networking architecture consists of:

* **Networking Service** (``ironic-networking``): A standalone service that
  manages network switch configurations via switch drivers
* **Switch Driver Framework**: Pluggable drivers for different network switch
  vendors (e.g., generic-switch implemented using networking-generic-switch)
* **ironic-networking Network Interface**: An Ironic network interface
  that integrates with the standalone networking service
* **RPC Communication**: Communication between conductor and networking service
  using JSON-RPC or oslo-messaging supported backends like rabbitmq

Configuring Driver Interfaces
=============================

Switch Driver Framework
-----------------------

The switch driver framework within the ``ironic-networking`` service provides:

* **Driver Factory**: Dynamically loads switch drivers via stevedore
* **Base Driver Interface**: Common API for all switch drivers
* **Generic Switch Driver**: Built-in driver, named ``generic-switch``, using
  networking-generic-switch
* **Driver Translators**: Convert generic switch configs to driver-specific
  formats

ironic-networking Network Interface
-----------------------------------

The ``ironic-networking`` network interface (enabled per-node) provides:

* Integration between Ironic nodes and the networking service
* Switchport configuration validation via JSON schemas
* Support for ports, and planned support for portgroups (LAG)
* State-based network configuration (cleaning, provisioning, rescuing, etc.)

Installation and Dependencies
=============================

The standalone networking service requires the ``networking-generic-switch``
library for the generic-switch driver. Install it from the driver requirements
file::

    $ pip install -r driver-requirements.txt

Configuration
=============

Authentication Strategies
-------------------------

The standalone networking service supports the following authentication
strategies for RPC communication between the Ironic conductor and the
networking service:

* ``keystone`` - Use OpenStack Identity service (Keystone) for authentication.
  Recommended for production OpenStack deployments.
* ``http_basic`` - HTTP Basic authentication using an Apache-format htpasswd
  file. Suitable for standalone deployments without Keystone.
* ``noauth`` - No authentication. **Not recommended for production** as it
  provides no security.

The authentication strategy is configured via the ``auth_strategy`` option,
which can be set globally in ``[DEFAULT]`` or per-service in the
``[ironic_networking_json_rpc]`` section.

Creating the htpasswd File
^^^^^^^^^^^^^^^^^^^^^^^^^^

When using ``http_basic`` authentication, create the htpasswd file::

   $ htpasswd -c -B /etc/ironic/htpasswd-rpc networking-rpc

Set appropriate permissions::

   $ chmod 600 /etc/ironic/htpasswd-rpc
   $ chown ironic:ironic /etc/ironic/htpasswd-rpc


RPC Transport Options
---------------------

Communication between the Ironic conductor and the networking service can use
one of two transport mechanisms:

* ``json-rpc`` - Direct JSON-RPC over HTTP/HTTPS. Simpler to configure for
  standalone deployments.
* ``oslo_messaging`` - Oslo.messaging with a message broker (e.g., RabbitMQ).
  Recommended for production OpenStack deployments as it provides better
  reliability and is consistent with other OpenStack services.

Example: Production Configuration with Keystone and Oslo Messaging
------------------------------------------------------------------

This example shows a production-ready configuration using Keystone
authentication and RabbitMQ for RPC transport.

**Main Ironic Configuration (ironic.conf)**

.. code-block:: ini

   [DEFAULT]
   enabled_network_interfaces = ironic-networking,noop
   auth_strategy = keystone
   rpc_transport = oslo_messaging
   transport_url = rabbit://ironic:password@rabbit-host:5672/

   [ironic_networking]
   rpc_transport = oslo_messaging
   idle_network = access/native_vlan=123
   inspection_network = access/native_vlan=123

   [keystone_authtoken]
   www_authenticate_uri = http://keystone-host:5000
   auth_url = http://keystone-host:5000
   auth_type = password
   project_domain_name = Default
   user_domain_name = Default
   project_name = service
   username = ironic
   password = <ironic-service-password>

   [oslo_messaging_rabbit]
   rabbit_host = rabbit-host
   rabbit_userid = ironic
   rabbit_password = password

**Networking Service Configuration (ironic-networking.conf)**

.. code-block:: ini

   [DEFAULT]
   auth_strategy = keystone
   rpc_transport = oslo_messaging
   transport_url = rabbit://ironic:password@rabbit-host:5672/

   [keystone_authtoken]
   www_authenticate_uri = http://keystone-host:5000
   auth_url = http://keystone-host:5000
   auth_type = password
   project_domain_name = Default
   user_domain_name = Default
   project_name = service
   username = ironic-networking
   password = <ironic-networking-service-password>

   [oslo_messaging_rabbit]
   rabbit_host = rabbit-host
   rabbit_userid = ironic
   rabbit_password = password

   [ironic_networking]
   enabled_switch_drivers = generic-switch
   driver_config_dir = /var/lib/ironic/networking
   switch_config_file = /etc/ironic/networking/switch-configs.conf

Example: Standalone Configuration with HTTP Basic Auth and JSON-RPC
-------------------------------------------------------------------

This example shows a simpler configuration suitable for standalone deployments
without Keystone or a message broker.

**Main Ironic Configuration (ironic.conf)**

.. code-block:: ini

   [DEFAULT]
   enabled_network_interfaces = ironic-networking,noop
   auth_strategy = http_basic
   http_basic_auth_user_file = /etc/ironic/htpasswd

   [ironic_networking_json_rpc]
   auth_strategy = http_basic
   http_basic_auth_user_file = /etc/ironic/htpasswd-rpc
   host_ip = localhost
   port = 6190
   username = networking-rpc
   password = <rpc-password>

   [ironic_networking]
   rpc_transport = json-rpc
   idle_network = access/native_vlan=123
   inspection_network = access/native_vlan=123

**Networking Service Configuration (ironic-networking.conf)**

.. code-block:: ini

   [DEFAULT]
   auth_strategy = http_basic
   http_basic_auth_user_file = /etc/ironic/htpasswd
   rpc_transport = json-rpc

   [ironic_networking_json_rpc]
   auth_strategy = http_basic
   http_basic_auth_user_file = /etc/ironic/htpasswd-rpc
   host_ip = localhost
   port = 6190
   username = networking-rpc
   password = <rpc-password>

   [ssl]
   cert_file = /etc/ironic/ssl/tls.crt
   key_file = /etc/ironic/ssl/tls.key

   [ironic_networking]
   enabled_switch_drivers = generic-switch
   driver_config_dir = /var/lib/ironic/networking
   switch_config_file = /etc/ironic/networking/switch-configs.conf

Switch Configuration File (switch-configs.conf)
-----------------------------------------------

Create ``/etc/ironic/switch-configs.conf`` with your switch definitions.
This file uses a generic format that is translated to driver-specific
configuration by the driver adapter.

.. Note:: The networking service auto-generates driver-specific config files
          in ``driver_config_dir`` from this generic configuration. You should
          not manually create files in that directory.

Generic Format
^^^^^^^^^^^^^^

Each switch is defined in its own section with a name of your choice:

.. code-block:: ini

   [switch-name]
   # Switch connection information
   address = 192.168.1.10
   username = admin
   password = secretpassword

   # Driver type.  Currently only "generic-switch"
   driver_type = generic-switch

   # Device type.  Value specific to the driver type.  (i.e., if driver type is
   # generic-switch then device type should be one of the
   # networking-generic-switch "generic_switch.devices" entry points.
   # Example netmiko_dell_os10).
   device_type = netmiko_cisco_ios

   # Switch MAC address (for identification)
   mac_address = 00:11:22:33:44:55

   # Optional: SSH port (default: 22)
   port = 22

   # Optional: Enable secret for privileged mode
   enable_secret = enablepassword

   # Optional: SSH key file instead of password
   # key_file = /path/to/ssh/key

   # Optional: Save configuration after changes (default: false)
   persist = false

   # Optional: Filter which VLAN instance are allowed on the switch
   allowed_vlans = 100,200-210

Example with multiple switches:

.. code-block:: ini

   [tor-switch-1]
   address = 192.168.1.10
   username = admin
   password = switch1pass
   device_type = cisco_ios
   enable_secret = enablepass
   persist = true
   mac_address = aa:bb:cc:dd:ee:01

   [tor-switch-2]
   address = 192.168.1.11
   username = admin
   password = switch2pass
   device_type = arista_eos
   mac_address = aa:bb:cc:dd:ee:02


Supported Device Types
^^^^^^^^^^^^^^^^^^^^^^

The generic-switch driver supports any device type supported by the
``networking-generic-switch`` library.  Common types include:

* ``cisco_ios`` - Cisco IOS switches
* ``cisco_nxos`` - Cisco Nexus switches
* ``arista_eos`` - Arista EOS switches
* ``dell_os10`` - Dell OS10 switches
* ``juniper_junos`` - Juniper Junos switches
* ``ovs_linux`` - Open vSwitch (for testing)

See the networking-generic-switch documentation for the complete list of
supported device types.

Node Configuration
==================

Configuring Network Interface
-----------------------------

Set nodes to use the ``ironic-networking`` network interface:

.. code-block:: console

   $ openstack baremetal node set <node> \
       --network-interface ironic-networking

Override Default Networks (Optional)
------------------------------------

You can override the global network configuration per-node using ``driver_info``:

.. code-block:: console

   $ openstack baremetal node set <node> \
       --driver-info provisioning_network=access/native_vlan=250 \
       --driver-info cleaning_network=access/native_vlan=150

Port Configuration with Switchport Information
----------------------------------------------

Each port must have ``local_link_connection`` and switchport configuration
in the ``extra`` field.  The ``local_link_connection`` information is expected
to be populated automatically from LLDP at the end of inspection, or manually
if automatic inspection is not used or LLDP is not available.

The ``local_link_connection`` identifies the physical switch and port:

.. code-block:: json

   {
     "switch_id": "aa:bb:cc:dd:ee:01",
     "port_id": "GigabitEthernet1/0/1",
     "switch_info": "tor-switch-1"
   }

The ``switch_id`` should match either the switch's MAC address or the name
used in ``switch-configs.conf``.

Switchport Configuration Schema
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

The switchport configuration in ``port.extra.switchport`` must conform to this
schema:

**Required fields:**

* ``mode`` (string): Port mode - ``access``, ``trunk``, or ``hybrid``
* ``native_vlan`` (integer): Native VLAN ID (1-4094)

**Optional fields:**

* ``allowed_vlans`` (array of integers): Allowed VLAN IDs for trunk/hybrid
  modes (required if mode is trunk or hybrid)
* ``mtu`` (integer): Maximum transmission unit (max: 9216)

**Validation rules:**

* Access mode: ``allowed_vlans`` must NOT be specified
* Trunk/Hybrid mode: ``allowed_vlans`` must be specified with at least one VLAN
* PXE-enabled ports: Must use ``access`` mode

Example: Access Mode Port
^^^^^^^^^^^^^^^^^^^^^^^^^
.. Note:: These examples manually set the local-link-connection info, but as
  described earlier, these values could be received via LLDP during inspection
  if both are enabled and available.

.. code-block:: console

   $ openstack baremetal port create \
       --node <node-uuid> \
       --address aa:bb:cc:dd:ee:ff \
       --local-link-connection switch_id=aa:bb:cc:dd:ee:01 \
       --local-link-connection port_id=GigabitEthernet1/0/1 \
       --local-link-connection switch_info=tor-switch-1 \
       --extra switchport='{"mode": "access", "native_vlan": 100}' \
       --pxe-enabled true

Example: Trunk Mode Port
^^^^^^^^^^^^^^^^^^^^^^^^

.. code-block:: console

   $ openstack baremetal port create \
       --node <node-uuid> \
       --address aa:bb:cc:dd:ee:ff \
       --local-link-connection switch_id=aa:bb:cc:dd:ee:01 \
       --local-link-connection port_id=GigabitEthernet1/0/2 \
       --local-link-connection switch_info=tor-switch-1 \
       --extra switchport='{"mode": "trunk", "native_vlan": 1, "allowed_vlans": [100, 200, 300]}' \
       --pxe-enabled false

Running the Networking Service
==============================

Standalone Mode
---------------

Run the networking service as a separate process:

.. code-block:: console

   $ ironic-networking --config-file /etc/ironic/ironic.conf

Verify Service Status
---------------------

Check that the service initialized correctly by examining logs.  You should
see log messages indicating:

* Number of driver-specific config files generated
* List of loaded switch drivers
* Networking service initialization on the configured host

Example output::

   Networking service initialized with switch drivers: generic-switch
   Generated 3 driver-specific config files during init

Troubleshooting
===============

Common Issues
-------------

**No switch drivers loaded**

If you see::

   No switch drivers loaded - networking service will operate without switch
   management capabilities

Check:

* ``enabled_switch_drivers`` is set in ``[ironic_networking]`` section
* Switch driver is installed (e.g., ``networking-generic-switch``)
* Driver entry point exists in ``ironic.networking.switch_drivers`` namespace

**Switch not found errors**

If switch operations fail with ``SwitchNotFound``:

* Verify ``switch_id`` in port's ``local_link_connection`` matches a switch
  in ``switch-configs.conf``
* Check switch driver configuration was generated in ``driver_config_dir``
* Ensure switch MAC address or name matches exactly

**RPC communication failures**

For JSON-RPC connection issues:

* Verify ``host_ip`` and ``port`` in ``[ironic_networking_json_rpc]`` section
* Ensure networking service is running and listening
* Check firewall rules allow traffic on the configured port

For Oslo Messaging issues:

* Verify message bus (RabbitMQ) is running and accessible
* Check credentials in ``[oslo_messaging_rabbit]`` section
* Ensure conductor and networking service use the same transport URL

Debugging
---------

Enable debug logging in ``ironic.conf``:

.. code-block:: ini

   [DEFAULT]
   debug = true
   log_file = /var/log/ironic/ironic-networking.log

This will show detailed information about:

* Switch driver loading and configuration
* RPC method calls and parameters
* Switch operations and responses
* VLAN validation results

Advanced Configuration
======================

VLAN Range Restrictions
-----------------------

The ``allowed_vlans`` configuration option restricts which VLAN IDs can be
used for port configuration. This setting can be configured globally in
``ironic.conf`` and optionally overridden on a per-switch basis in the
switch configuration file.

**Allow All VLANs (Default)**

If ``allowed_vlans`` is not specified or set to ``None``, all VLAN IDs
(1-4094) are permitted:

.. code-block:: ini

   [ironic_networking]
   # Not specified - all VLANs allowed (default behavior)

**Block All VLANs**

To prevent any VLAN configuration (useful for testing or maintenance):

.. code-block:: ini

   [ironic_networking]
   # Empty list - no VLANs allowed
   allowed_vlans = []

**Allow Specific VLANs**

Restrict to specific VLAN IDs using individual values, ranges, or a
combination of both. Values are specified as a comma-separated list without
square brackets:

.. code-block:: ini

   [ironic_networking]
   # Allow individual VLANs (comma-separated)
   allowed_vlans = 100,101,102,1000

   # Allow VLAN ranges
   allowed_vlans = 100-199,1000-1099

   # Mixed individual and range notation
   allowed_vlans = 100,101,102-104,106,200-299,1000

The last example allows VLANs: 100, 101, 102, 103, 104, 106, 200-299, and
1000, but denies 105 and all others outside the specified ranges.

**Per-Switch VLAN Restrictions**

Override global restrictions for specific switches in the switch
configuration file:

.. code-block:: ini

   [tor-switch-1]
   address = 192.168.1.10
   username = admin
   password = switchpass
   device_type = cisco_ios
   # Only specific VLANs on this switch
   allowed_vlans = 200-299

   [tor-switch-2]
   address = 192.168.1.11
   username = admin
   password = switchpass
   device_type = cisco_ios
   # Only allow a different set of VLANs on this switch
   allowed_vlans = 100-199,1000

**Validation Behavior**

When a port configuration operation is attempted:

1. The service checks if switch-specific ``allowed_vlans`` is configured
2. If not found, falls back to global ``[ironic_networking] allowed_vlans``
3. If neither is specified, all VLANs (1-4094) are allowed
4. If configured, any VLAN outside the allowed set will cause the operation
   to fail.

The validation applies to both ``native_vlan`` and all VLANs in the
``allowed_vlans`` list for trunk/hybrid ports.

Network State Transitions
-------------------------

The ironic-networking interface manages switch configurations based on
node state and will configure the switch port to the corresponding network
configuration.

* **Inspection**: Configures ``inspection_network`` (if set)
* **Cleaning**: Configures ``cleaning_network`` (if set)
* **Provisioning**: Configures ``provisioning_network`` (if set)
* **Rescuing**: Configures ``rescuing_network`` (if set)
* **Servicing**: Configures ``servicing_network`` (if set)
* **Idle**: Reverts to ``idle_network`` (if set)

.. note::
   The ``idle_network`` represents the default VLAN configuration that ports
   should be set to when no specific network is required for the node's current
   state. This network is used whenever a node transitions to a state that
   doesn't have an explicit network configuration defined (e.g., ``available``,
   ``enroll``, ``manageable``). It's also used when exiting states like
   cleaning, provisioning, or rescuing if no other network applies.

   The idle network should be configured to allow connectivity back to the
   Ironic API for inspection and management operations. If ``idle_network`` is
   not configured, switch ports will not be configured (or will assume the
   switch's own global default) when transitioning to idle states.

Security Considerations
=======================

Credential Management
---------------------

* Store switch passwords securely, not in plain text
* Use SSH keys (``key_file``) instead of passwords when possible
* Restrict file permissions on ``switch-configs.conf``::

   $ chmod 600 /etc/ironic/switch-configs.conf
   $ chown ironic:ironic /etc/ironic/switch-configs.conf


Switch Access Control
---------------------

* Use dedicated service accounts with minimal privileges for switch access
* Enable audit logging on switches for Ironic service account actions
* Regularly rotate switch credentials

Migration from Neutron
======================

If migrating from Neutron-based networking to standalone networking:

#. Ensure all nodes are in a stable state (``available`` or ``active``)
#. Update node configuration to use ``ironic-networking`` interface::

    $ openstack baremetal node set <node> \
        --network-interface ironic-networking

#. Add switchport configuration to ports (see Port Configuration section)
#. Configure and start the ``ironic-networking`` service
#. Test with a single node before migrating all nodes

.. note:: Ironic supports using different network interfaces on different nodes.
          Therefore, it is possible to have some nodes migrated to the new
          ``ironic-networking`` network interface while others are still using
          the ``neutron`` network interface.

Limitations and Future Work
===========================

Current Limitations
-------------------

* LAG operations are not yet implemented
* Limited to switches supported by networking-generic-switch
* No runtime reload of Ironic switch configuration file.  Requires
  ironic-networking service restart.
* Running multiple instances of ironic-networking for high-availability is not
  supported.

References
==========

* :doc:`/admin/dhcp-less`
* :doc:`/admin/networking`
* :ref:`configure-networking`
* `networking-generic-switch documentation <https://networking-generic-switch.readthedocs.io/>`_
