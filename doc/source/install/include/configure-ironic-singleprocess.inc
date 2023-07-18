Configuring single-process ironic
---------------------------------

As an alternative to starting separate API and conductor instances, you can
start ``ironic`` services that combine an API and a conductor in the same
process. This may be particularly beneficial in environments with limited
resources and low number of nodes to handle.

.. note:: This feature is available starting with the Yoga release series.

#. Start with setting up the environment as described in both `Configuring
   ironic-api service`_ and `Configuring ironic-conductor service`_, but do not
   start any services. Merge configuration options into a single configuration
   file.

   .. note::
      Any RPC settings will only take effect if you have more than one combined
      service started or if you have additional conductors.

      If you don't plan to have more than one conductor, you can disable the
      RPC completely:

      .. code-block:: ini

        [DEFAULT]
        rpc_transport = none

#. Stop existing services if they are already started:

   RHEL/CentOS/SUSE::

       sudo systemctl stop openstack-ironic-api
       sudo systemctl stop openstack-ironic-conductor

   Ubuntu/Debian::

       sudo service ironic-api stop
       sudo service ironic-conductor stop

#. Start or restart the ironic service:

   RHEL/CentOS/SUSE::

       sudo systemctl restart openstack-ironic

   Ubuntu/Debian::

       sudo service ironic restart
