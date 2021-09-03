Developing deploy and clean steps
=================================

Deploy steps basics
-------------------

To support customized deployment step, implement a new method in an interface
class and use the decorator ``deploy_step`` defined in
``ironic/drivers/base.py``. For example, we will implement a ``do_nothing``
deploy step in the ``AgentDeploy`` class.

.. code-block:: python

  from ironic.drivers.modules import agent

  class AgentDeploy(agent.AgentDeploy):

      @base.deploy_step(priority=200, argsinfo={
          'test_arg': {
              'description': (
                  "This is a test argument."
              ),
              'required': True
          }
      })
      def do_nothing(self, task, **kwargs):
          return None

If you want to completely replace the deployment procedure, but still have the
agent up and running, inherit ``CustomAgentDeploy``:

.. code-block:: python

  from ironic.drivers.modules import agent

  class AgentDeploy(agent.CustomAgentDeploy):

      def validate(self, task):
          super().validate(task)
          # ... custom validation

      @base.deploy_step(priority=80)
      def my_write_image(self, task, **kwargs):
          pass  # ... custom image writing

      @base.deploy_step(priority=70)
      def my_configure_bootloader(self, task, **kwargs):
          pass  # ... custom bootloader configuration

After deployment of the baremetal node, check the updated deploy steps::

    baremetal node show $node_ident -f json -c driver_internal_info

The above command outputs the ``driver_internal_info`` as following::

  {
    "driver_internal_info": {
      ...
      "deploy_steps": [
        {
          "priority": 200,
          "interface": "deploy",
          "step": "do_nothing",
          "argsinfo":
            {
              "test_arg":
                {
                  "required": True,
                  "description": "This is a test argument."
                }
            }
        },
        {
          "priority": 100,
          "interface": "deploy",
          "step": "deploy",
          "argsinfo": null
        }
      ],
      "deploy_step_index": 1
    }
  }

In-band deploy steps (deploy steps that are run inside the ramdisk) have to be
implemented in a custom :ironic-python-agent-doc:`IPA hardware manager
<contributor/hardware_managers.html#custom-hardwaremanagers-and-deploying>`.
All in-band deploy steps must have priorities between 41 and 99, see
:ref:`node-deployment-core-steps` for details.

Clean steps basics
------------------

Clean steps are written similarly to deploy steps, but are executed during
:doc:`cleaning </admin/cleaning>`. Steps with priority > 0 are executed during
automated cleaning, all steps can be executed explicitly during manual
cleaning. Unlike deploy steps, clean steps are commonly found in these
interfaces:

``bios``
    Steps that apply BIOS settings, see `Implementing BIOS settings`_.
``deploy``
    Steps that undo the effect of deployment (e.g. erase disks).
``management``
    Additional steps that use the node's BMC, such as out-of-band firmware
    update or BMC reset.
``raid``
    Steps that build or tear down RAID, see `Implementing RAID`_.

.. note::
   When designing a new step for your driver, try to make it consistent with
   existing steps on other drivers.

Just as deploy steps, in-band clean steps have to be
implemented in a custom :ironic-python-agent-doc:`IPA hardware manager
<contributor/hardware_managers.html#custom-hardwaremanagers-and-cleaning>`.

Asynchronous steps
------------------

If the step returns ``None``, ironic assumes its execution is finished and
proceeds to the next step. Many steps are executed asynchronously; in this case
you need to inform ironic that the step is not finished. There are several
possibilities:

Combined in-band and out-of-band step
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

If your step starts as out-of-band and then proceeds as in-band (i.e. inside
the agent), you only need to return ``CLEANWAIT``/``DEPLOYWAIT`` from
the step.

.. code-block:: python

    from ironic.drivers import base
    from ironic.drivers.modules import agent
    from ironic.drivers.modules import agent_base
    from ironic.drivers.modules import agent_client
    from ironic.drivers.modules import deploy_utils

    class MyDeploy(agent.CustomAgentDeploy):
        ...

        @base.deploy_step(priority=80)
        def my_deploy(self, task):
            ...
            return deploy_utils.get_async_step_return_state(task.node)

        # Usually you can use a more high-level pattern:

        @base.deploy_step(priority=60)
        def my_deploy2(self, task):
            new_step = {'interface': 'deploy',
                        'step': 'my_deploy2',
                        'args': {...}}
            client = agent_client.get_client(task)
            return agent_base.execute_step(task, new_step, 'deploy',
                                           client=client)

.. warning::
   This approach only works for steps implemented on a ``deploy``
   interface that inherits agent deploy.

Execution on reboot
~~~~~~~~~~~~~~~~~~~

Some steps are executed out-of-band, but require a reboot to complete. Use the
following pattern:

.. code-block:: python

    from ironic.drivers import base
    from ironic.drivers.modules import deploy_utils

    class MyManagement(base.ManagementInterface):
        ...

        @base.clean_step(priority=0)
        def my_action(self, task):
            ...

            # Tell ironic that...
            deploy_utils.set_async_step_flags(
                node,
                # ... we're waiting for IPA to come back after reboot
                reboot=True,
                # ... the current step is done
                skip_current_step=True)

            return deploy_utils.reboot_to_finish_step(task)

Implementing RAID
-----------------

RAID is implemented via deploy and clean steps in the ``raid`` interfaces.
By convention they have the following signatures:

.. code-block:: python

    from ironic.drivers import base

    class MyRAID(base.RAIDInterface):

        @base.clean_step(priority=0, abortable=False, argsinfo={
            'create_root_volume': {
                'description': (
                    'This specifies whether to create the root volume. '
                    'Defaults to `True`.'
                ),
                'required': False
            },
            'create_nonroot_volumes': {
                'description': (
                    'This specifies whether to create the non-root volumes. '
                    'Defaults to `True`.'
                ),
                'required': False
            },
            'delete_existing': {
                'description': (
                    'Setting this to `True` indicates to delete existing RAID '
                    'configuration prior to creating the new configuration. '
                    'Default value is `False`.'
                ),
                'required': False,
            }
        })
        def create_configuration(self, task, create_root_volume=True,
                                 create_nonroot_volumes=True,
                                 delete_existing=False):
            pass

        @base.clean_step(priority=0)
        @base.deploy_step(priority=0)
        def delete_configuration(self, task):
            pass

        @base.deploy_step(priority=0,
                          argsinfo=base.RAID_APPLY_CONFIGURATION_ARGSINFO)
        def apply_configuration(self, task, raid_config,
                                create_root_volume=True,
                                create_nonroot_volumes=False,
                                delete_existing=False):
            pass

Notes:

* ``create_configuration`` only works as a clean step, during deployment
  ``apply_configuration`` is used instead.
* ``apply_configuration`` accepts the target RAID configuration explicitly,
  while ``create_configuration`` uses the node's ``target_raid_config`` field.
* Priorities default to 0 since RAID should not be built by default.

Implementing BIOS settings
--------------------------

BIOS is implemented via deploy and clean steps in the ``raid`` interfaces.
By convention they have the following signatures:

.. code-block:: python

    from ironic.drivers import base

    _APPLY_CONFIGURATION_ARGSINFO = {
        'settings': {
            'description': (
                'A list of BIOS settings to be applied'
            ),
            'required': True
        }
    }

    class MyBIOS(base.BIOSInterface):

        @base.clean_step(priority=0)
        @base.deploy_step(priority=0)
        @base.cache_bios_settings
        def factory_reset(self, task):
            pass

        @base.clean_step(priority=0, argsinfo=_APPLY_CONFIGURATION_ARGSINFO)
        @base.deploy_step(priority=0, argsinfo=_APPLY_CONFIGURATION_ARGSINFO)
        @base.cache_bios_settings
        def apply_configuration(self, task, settings):
            pass

Notes:

* Both ``factory_reset`` and ``apply_configuration`` can be used as deploy
  and clean steps.
* The ``cache_bios_settings`` decorator is used to ensure that the settings
  cached in the ironic database is updated.
* Priorities default to 0 since BIOS settings should not be modified
  by default.
