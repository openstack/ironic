Developing a new Deploy Step
============================

To support customized deployment step, implement a new method in an interface
class and use the decorator ``deploy_step`` defined in
``ironic/drivers/base.py``. For example, we will implement a ``do_nothing``
deploy step in the ``AgentDeploy`` class.

.. code-block:: python

  class AgentDeploy(AgentDeployMixin, base.DeployInterface):
      ...

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

After deployment of the baremetal node, check the updated deploy steps::

    openstack baremetal node show $node_ident -f json -c driver_internal_info

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

.. note::

    Similarly, clean steps can be implemented using the ``clean_step``
    decorator.
