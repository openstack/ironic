=====
Steps
=====

What are steps?
===============

Steps are exactly that, steps to achieve a goal, and in most cases, they
are what an operator requested.

However, originally they were the internal list of actions to achieve to
perform *automated cleaning*. The conductor would determine a list of
steps or actions to take by generating a list of steps from data the
conductor via drivers, the ``ironic-python-agent``, and any loaded
hardware managers determined to be needed.

As time passed and Ironic's capabilities were extended, this was extended
to *manual cleaning*, and later into *deploy steps*, and *deploy templates*
allowing an operator to request for firmware to be updated by a driver, or
RAID to be configured by the agent prior to the machine being released
to the end user for use.

Reserved Functional Steps
=========================
In the execution of the cleaning, and deployment steps frameworks, some step
names are reserved for specific functions which can be invoked by a user to
perform specific actions.

+-----------+----------------------------------------------------------+
| Step Name | Description                                              |
+-----------+----------------------------------------------------------+
| hold      | Pauses the execution of the steps by moving the node     |
|           | from the current ``deploy wait`` or ``clean wait`` state |
|           | to the appropriate "hold" state, such as ``deploy hold`` |
|           | or ``clean hold``. The process can be resumed by sending |
|           | a ``unhold`` verb to the provision state API endpoint    |
|           | which will result in the process resuming upon the next  |
|           | heartbeat operation. During this time, heartbeat         |
|           | operations will continue be recorded by Ironic, but will |
|           | not be acted upon, preventing the node from timing out.  |
|           |                                                          |
|           | This step cannot be used against a child node in the     |
|           | context of being requested when executing against a      |
|           | parent node.                                             |
|           |                                                          |
|           | The use case for this verb is if you have external       |
|           | automation or processes which need to be executed in the |
|           | entire process to achieve the overall goal.              |
+-----------+----------------------------------------------------------+
| power_on  | Powers on the node, which may be useful if a node's      |
|           | power must be toggled multiple times to enable           |
|           | embedded behavior such as to boot from network.          |
|           | This step can be executed against child nodes.           |
+-----------+----------------------------------------------------------+
| power_off | Turn the node power off via the conductor.               |
|           | This step can be used against child nodes. When used     |
|           | outside of the context of a child node, any agent token  |
|           | metadata is also removed as so the machine can reboot    |
|           | back to the agent, if applicable.                        |
+-----------+----------------------------------------------------------+
| reboot    | Reboot the node utilizing the conductor. This generally  |
|           | signals for power to be turned off and back on, however  |
|           | driver specific code may request an CPU interrupt based  |
|           | reset. This step can be executed on child nodes.         |
+-----------+----------------------------------------------------------+
| wait      | Causes a brief pause in the overall step execution which |
|           | pauses until the next heartbeat operation, unless a      |
|           | seconds argument is provided. If a *seconds* argument is |
|           | provided, then the step execution will pause for the     |
|           | requested amount of time.                                |
+-----------+----------------------------------------------------------+


In the these cases, the interface upon which the method is expected is
ignored, and the step is acted upon based upon just the step's name.


Example
-------

In this example, we utilize the cleaning step ``erase_devices`` and then
trigger hold of the node. In this specific case the node will enter
a ``clean hold`` state.

.. code-block:: json

  {
    "target":"clean",
    "clean_steps": [{
      "interface": "deploy",
      "step": "erase_devices"
    },
    {
      "interface": "deploy",
      "step": "hold"
    }]
  }

Once you have completed whatever action which needed to be performed while
the node was in a held state, you will need to issue an unhold provision
state command, via the API or command line to inform the node to proceed.

Set the environment
===================

When using steps with the functionality to execute on child nodes,
i.e. nodes who a populated ``parent_node`` field, you always want to
ensure you have set the environment appropriately for your next action.

For example, if you are executing steps against a parent node, which then
execute against a child node via the ``execute_on_child_nodes`` step option,
and it requires power to be on, you will want to explicitly
ensure the power is on for the parent node **unless** the child node can
operate independently, as signaled through the driver_info option
``has_dedicated_power_supply`` on the child node. Power is an obvious
case because Ironic has guarding logic internally to attempt to power-on the
parent node, but it cannot be an after thought due to internal task locking.

Power specifically aside, the general principle applies to the execution
of all steps. You need always want to build upon the prior step or existing
existing known state of the system.

.. NOTE::
   Ironic will attempt to ensure power is active for a ``parent_node`` when
   powering on a child node. Conversely, Ironic will also attempt to power
   down child nodes if a parent node is requested to be turned off, unless
   the ``has_dedicated_power_supply`` option is set for the child node.
   This pattern of behavior prevents parent nodes from being automatically
   powered back on should a child node be left online.

BMC Clock Verification Step (Verify Phase)
===========================================

The Redfish management interface includes a verify step called
``verify_bmc_clock`` which automatically checks and sets the BMC
clock during node registration.

This step compares the system time on the conductor with the BMC's
time reported via Redfish. If the clock differs by more than one
second, Ironic updates the BMC's clock to match the conductor's UTC time.

This step runs automatically if enabled and the node
supports the Redfish interface.

How to Enable
---------------
 The feature is controlled by the following configuration option
 in `` ironic.conf``:

 .. code-block:: ini

    [redfish]
    enable_verify_bmc_clock = true

 By default, this option is set to ``false``. To enable it, set it to ``true`` and
 restart the ``ironic conductor``.

When It Runs
---------------

``verify_bmc_clock`` step is triggered during the automated verify step of the
node registration, before inspection and deployment.

 Note:

- If the BMC does not support setting the clock via Redfish,
  the step will fail.

- If the time cannot be synchronized within 1 second, the step will
  raise a ``NodeVerifyFailure``.

- If the configuration option is disabled, the step is skipped.

- ``verify_bmc_clock`` is defined with a priority of 1 and
  is not interruptible.

- This is different from the manual ``clean`` step ``set_bmc_clock``
  which allows explicit datatime setting through the API.
