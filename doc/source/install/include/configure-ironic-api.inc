Configuring ironic-api service
------------------------------

#. The Bare Metal service stores information in a database. This guide uses the
   MySQL database that is used by other OpenStack services.

   Configure the location of the database via the ``connection`` option. In the
   following, replace ``IRONIC_DBPASSWORD`` with the password of your
   ``ironic`` user, and replace ``DB_IP`` with the IP address where the DB
   server is located:

   .. code-block:: ini

      [database]

      # The SQLAlchemy connection string used to connect to the
      # database (string value)
      connection=mysql+pymysql://ironic:IRONIC_DBPASSWORD@DB_IP/ironic?charset=utf8

#. Configure the ironic-api service to use the RabbitMQ message broker by
   setting the following option. Replace ``RPC_*`` with appropriate
   address details and credentials of RabbitMQ server:

   .. code-block:: ini

      [DEFAULT]

      # A URL representing the messaging driver to use and its full
      # configuration. (string value)
      transport_url = rabbit://RPC_USER:RPC_PASSWORD@RPC_HOST:RPC_PORT/

   Alternatively, you can use JSON RPC for interactions between
   ironic-conductor and ironic-api. Enable it in the configuration and provide
   the keystone credentials to use for authentication:

   .. code-block:: ini

      [DEFAULT]

      rpc_transport = json-rpc

      [json_rpc]

      # Authentication type to load (string value)
      auth_type = password

      # Authentication URL (string value)
      auth_url=https://IDENTITY_IP:5000/

      # Username (string value)
      username=ironic

      # User's password (string value)
      password=IRONIC_PASSWORD

      # Project name to scope to (string value)
      project_name=service

      # Domain ID containing project (string value)
      project_domain_id=default

      # User's domain id (string value)
      user_domain_id=default

   If you use port other than the default 8089 for JSON RPC, you have to
   configure it, for example:

   .. code-block:: ini

      [json_rpc]
      port = 9999

#. Configure the ironic-api service to use these credentials with the Identity
   service. Replace ``PUBLIC_IDENTITY_IP`` with the public IP of the Identity
   server, ``PRIVATE_IDENTITY_IP`` with the private IP of the Identity server,
   replace ``IRONIC_PASSWORD`` with the password you chose for the
   ``ironic`` user in the Identity service and replace ``MEMCACHED_SERVER``
   with the hostname of the memcached server:

   .. code-block:: ini

      [DEFAULT]

      # Authentication strategy used by ironic-api: one of
      # "keystone" or "noauth". "noauth" should not be used in a
      # production environment because all authentication will be
      # disabled. (string value)
      auth_strategy=keystone

      [keystone_authtoken]

      # Authentication type to load (string value)
      auth_type=password

      # Complete public Identity API endpoint (string value)
      www_authenticate_uri=http://PUBLIC_IDENTITY_IP:5000

      # Complete admin Identity API endpoint. (string value)
      auth_url=http://PRIVATE_IDENTITY_IP:5000

      # Service username. (string value)
      username=ironic

      # Service account password. (string value)
      password=IRONIC_PASSWORD

      # Service tenant name. (string value)
      project_name=service

      # Domain name containing project (string value)
      project_domain_name=Default

      # User's domain name (string value)
      user_domain_name=Default

      # memcached setting (string value)
      memcached_servers=MEMCACHED_SERVER:11211

#. Create the Bare Metal service database tables:

   .. code-block:: bash

      $ ironic-dbsync --config-file /etc/ironic/ironic.conf create_schema

#. Restart the ironic-api service:

   RHEL/CentOS/SUSE::

       sudo systemctl restart openstack-ironic-api

   Ubuntu/Debian::

       sudo service ironic-api restart
