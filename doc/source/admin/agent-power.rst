=================================
Deploying without BMC Credentials
=================================

The Bare Metal service usually requires BMC credentials for all provisioning
operations. Starting with the Victoria release series there is limited support
for inspection, cleaning and deployments without the credentials.

.. warning::
   This feature is experimental and only works in a limited scenario. When
   using it, you have to be prepared to provide BMC credentials in case of
   a failure or any non-supported actions.

How it works
============

The expected workflow is as follows:

#. The node is discovered by manually powering it on and gets the
   `manual-management` hardware type and `agent` power interface.

   If discovery is not used, a node can be enrolled through the API and then
   powered on manually.

#. The operator moves the node to `manageable`. It works because the `agent`
   power only requires to be able to connect to the agent.

#. The operator moves the node to `available`. Cleaning happens normally via
   the already running agent. If reboot is needed, it is done by telling the
   agent to reboot the node in-band.

#. A user deploys the node. Deployment happens normally via the already
   running agent.

#. In the end of the deployment, the node is rebooted via the reboot command
   instead of power off+on.

Enabling
========

:doc:`fast-track` is a requirement for this feature to work. After enabling it,
adds the ``agent`` power interface and the ``manual-management`` hardware type
to the enabled list:

.. code-block:: ini

   [DEFAULT]
   enabled_hardware_types = manual-management
   enabled_management_interfaces = noop
   enabled_power_interfaces = agent

   [deploy]
   fast_track = true

As usual with the ``noop`` management, enable the networking boot fallback:

.. code-block:: ini

   [pxe]
   enable_netboot_fallback = true

If using discovery, :ironic-inspector-doc:`configure discovery in
ironic-inspector <user/usage.html#discovery>` with the default driver set
to ``manual-management``.

Limitations
===========

* Only the ``noop`` network interface is supported.

* Undeploy and rescue are not supported, you need to add BMC credentials first.

* If any errors happens in the process, recovery will likely require BMC
  credentials.

* Only rebooting is possible through the API, power on/off commands will fail.
