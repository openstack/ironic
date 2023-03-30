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
