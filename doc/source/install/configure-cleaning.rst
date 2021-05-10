.. _configure-cleaning:

Configure the Bare Metal service for cleaning
=============================================

.. note:: If you configured the Bare Metal service to do
          :ref:`automated_cleaning`
          (which is enabled by default), you will need to set the
          ``cleaning_network`` configuration option.

#. Note the network UUID (the `id` field) of the network you created in
   :ref:`configure-networking` or another network you created for cleaning:

   .. code-block:: console

      $ openstack network list

#. Configure the cleaning network UUID via the ``cleaning_network``
   option in the Bare Metal service configuration file
   (``/etc/ironic/ironic.conf``). In the following, replace ``NETWORK_UUID``
   with the UUID you noted in the previous step:

   .. code-block:: ini

      [neutron]
      cleaning_network = NETWORK_UUID

#. Restart the Bare Metal service's ironic-conductor:

   .. code-block:: console

      Fedora/RHEL8/CentOS8/SUSE:
        sudo systemctl restart openstack-ironic-conductor

      Ubuntu:
        sudo service ironic-conductor restart
