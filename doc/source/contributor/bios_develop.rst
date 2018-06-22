.. _bios_develop:

Developing BIOS Interface
=========================

To support a driver specific BIOS interface it is necessary to create a class
inheriting from the ``BIOSInterface`` class:

.. code-block:: python

  from ironic.drivers import base

  class ExampleBIOS(base.BIOSInterface):

      def get_properties(self):
          return {}

      def validate(self, task):
          pass

See :doc:`/contributor/drivers` for a detailed explanation of hardware type
and interface.

The ``get_properties`` and ``validate`` are methods that all driver interfaces
have. The hardware interface that supports BIOS settings should also implement
the following three methods:

* Implement a method named ``cache_bios_settings``. This method stores BIOS
  settings to the ``bios_settings`` table during cleaning operations and
  updates the ``bios_settings`` table when ``apply_configuration`` or
  ``factory_reset`` are successfully called.

  .. code-block:: python

    from ironic.drivers import base

    driver_client = importutils.try_import('driver.client')

    class ExampleBIOS(base.BIOSInterface):
        def __init__(self):
            if driver_client is None:
                raise exception.DriverLoadError(
                    driver=self.__class__.__name__,
                    reason=_("Unable to import driver library"))

        def cache_bios_settings(self, task):
            node_id = task.node.id
            node_info = driver_common.parse_driver_info(task.node)
            settings = driver_client.get_bios_settings(node_info)
            create_list, update_list, delete_list, nochange_list = (
                objects.BIOSSettingList.sync_node_setting(settings))

            if len(create_list) > 0:
                objects.BIOSSettingList.create(
                    task.context, node_id, create_list)
            if len(update_list) > 0:
                objects.BIOSSettingList.save(
                    task.context, node_id, update_list)
            if len(delete_list) > 0:
                delete_names = []
                for setting in delete_list:
                    delete_names.append(setting.name)
                objects.BIOSSettingList.delete(
                    task.context, node_id, delete_names)


  .. note::
     ``driver.client`` is vendor specific library to control and manage
     the bare metal hardware, for example: python-dracclient, sushy.

* Implement a method named ``factory_reset``. This method needs to use the
  ``clean_step`` decorator. It resets BIOS settings to factory default on the
  given node. It calls ``cache_bios_settings`` automatically to update
  existing ``bios_settings`` table once successfully executed.

  .. code-block:: python

    class ExampleBIOS(base.BIOSInterface):

        @base.clean_step(priority=0)
        def factory_reset(self, task):
            node_info = driver_common.parse_driver_info(task.node)
            driver_client.reset_bios_settings(node_info)

* Implement a method named ``apply_configuration``. This method needs to use
  the clean_step decorator. It takes the given BIOS settings and applies them
  on the node. It also calls ``cache_bios_settings`` automatically to update
  existing ``bios_settings`` table after successfully applying given settings
  on the node.

  .. code-block:: python

    class ExampleBIOS(base.BIOSInterface):

        @base.clean_step(priority=0, argsinfo={
            'settings': {
                'description': (
                    'A list of BIOS settings to be applied'
                ),
                'required': True
            }
        })
        def apply_configuration(self, task, settings):
            node_info = driver_common.parse_driver_info(task.node)
            driver_client.apply_bios_settings(node_info, settings)

  The ``settings`` parameter is a list of BIOS settings to be configured.
  for example::

      [
        {
          "setting name":
            {
              "name": "String",
              "value": "String"
            }
        },
        {
          "setting name":
            {
              "name": "String",
              "value": "String"
            }
        },
        ...
      ]
