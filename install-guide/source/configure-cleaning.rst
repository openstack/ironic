.. _configure-cleaning:

Configure the Bare Metal service for cleaning
=============================================

.. note:: If you configured the Bare Metal service to use `Node cleaning`_
          (which is enabled by default), you will need to set the
          ``cleaning_network_uuid`` configuration option.

.. _`Node cleaning`: http://docs.openstack.org/developer/ironic/newton/deploy/cleaning.html#node-cleaning

#. Note the network UUID (the `id` field) of the network you created in
   :ref:`configure-networking` or another network you created for cleaning:

   .. code-block:: console

      $ neutron net-list

#. Configure the cleaning network UUID via the ``cleaning_network_uuid``
   option in the Bare Metal service configuration file
   (``/etc/ironic/ironic.conf``). In the following, replace ``NETWORK_UUID``
   with the UUID you noted in the previous step:

   .. code-block:: ini

      [neutron]
      cleaning_network_uuid = NETWORK_UUID

#. Restart the Bare Metal service's ironic-conductor:

   .. code-block:: console

      Fedora/RHEL7/CentOS7:
        sudo systemctl restart openstack-ironic-conductor

      Ubuntu:
        sudo service ironic-conductor restart
