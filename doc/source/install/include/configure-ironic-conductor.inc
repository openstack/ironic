Configuring ironic-conductor service
------------------------------------

#. Replace ``HOST_IP`` with IP of the conductor host.

   .. code-block:: ini

      [DEFAULT]

      # IP address of this host. If unset, will determine the IP
      # programmatically. If unable to do so, will use "127.0.0.1".
      # (string value)
      my_ip=HOST_IP

   .. note::
      If a conductor host has multiple IPs, ``my_ip`` should
      be set to the IP which is on the same network as the bare metal nodes.

#. Configure the location of the database. Ironic-conductor should use the same
   configuration as ironic-api. Replace ``IRONIC_DBPASSWORD`` with the password
   of your ``ironic`` user, and replace DB_IP with the IP address where the DB
   server is located:

   .. code-block:: ini

      [database]

      # The SQLAlchemy connection string to use to connect to the
      # database. (string value)
      connection=mysql+pymysql://ironic:IRONIC_DBPASSWORD@DB_IP/ironic?charset=utf8

#. Configure the ironic-conductor service to use the RabbitMQ message broker by
   setting the following option. Ironic-conductor should use the same
   configuration as ironic-api. Replace ``RPC_*`` with appropriate
   address details and credentials of RabbitMQ server:

   .. code-block:: ini

      [DEFAULT]

      # A URL representing the messaging driver to use and its full
      # configuration. (string value)
      transport_url = rabbit://RPC_USER:RPC_PASSWORD@RPC_HOST:RPC_PORT/

   Alternatively, you can use JSON RPC for interactions between
   ironic-conductor and ironic-api. Enable it in the configuration and provide
   the keystone credentials to use for authenticating incoming requests (can
   be the same as for the API):

   .. code-block:: ini

      [DEFAULT]

      rpc_transport = json-rpc

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

   You can optionally change the host and the port the JSON RPC service will
   bind to, for example:

   .. code-block:: ini

      [json_rpc]
      host_ip = 192.168.0.10
      port = 9999

   .. warning::
      Hostnames of ironic-conductor machines must be resolvable by ironic-api
      services when JSON RPC is used.

#. Configure credentials for accessing other OpenStack services.

   In order to communicate with other OpenStack services, the Bare Metal
   service needs to use service users to authenticate to the OpenStack
   Identity service when making requests to other services.
   These users' credentials have to be configured in each
   configuration file section related to the corresponding service:

   * ``[neutron]`` - to access the OpenStack Networking service
   * ``[glance]`` - to access the OpenStack Image service
   * ``[swift]`` - to access the OpenStack Object Storage service
   * ``[cinder]`` - to access the OpenStack Block Storage service
   * ``[inspector]`` - to access the OpenStack Bare Metal Introspection
     service
   * ``[service_catalog]`` - a special section holding credentials
     the Bare Metal service will use to discover its own API URL endpoint
     as registered in the OpenStack Identity service catalog.

   For simplicity, you can use the same service user for all services.
   For backward compatibility, this should be the same user configured
   in the ``[keystone_authtoken]`` section for the ironic-api service
   (see "Configuring ironic-api service").
   However, this is not necessary, and you can create and configure separate
   service users for each service.

   Under the hood, Bare Metal service uses ``keystoneauth`` library
   together with ``Authentication plugin``, ``Session`` and ``Adapter``
   concepts provided by it to instantiate service clients.
   Please refer to `Keystoneauth documentation`_ for supported plugins,
   their available options as well as Session- and Adapter-related options
   for authentication, connection and endpoint discovery respectively.

   In the example below, authentication information for user to access the
   OpenStack Networking service is configured to use:

   * Networking service is deployed in the Identity service region named
     ``RegionTwo``, with only its ``public`` endpoint interface registered
     in the service catalog.
   * HTTPS connection with specific CA SSL certificate when making requests
   * the same service user as configured for ironic-api service
   * dynamic ``password`` authentication plugin that will discover
     appropriate version of Identity service API based on other
     provided options

     - replace ``IDENTITY_IP`` with the IP of the Identity server,
       and replace ``IRONIC_PASSWORD`` with the password you chose for the
       ``ironic`` user in the Identity service


   .. code-block:: ini

      [neutron]

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

      # PEM encoded Certificate Authority to use when verifying
      # HTTPs connections. (string value)
      cafile=/opt/stack/data/ca-bundle.pem

      # The default region_name for endpoint URL discovery. (string
      # value)
      region_name = RegionTwo

      # List of interfaces, in order of preference, for endpoint
      # URL. (list value)
      valid_interfaces=public


   By default, in order to communicate with another service, the Bare
   Metal service will attempt to discover an appropriate endpoint for
   that service via the Identity service's service catalog.
   The relevant configuration options from that service group in the Bare
   Metal service configuration file are used for this purpose.
   If you want to use a different endpoint for a particular service,
   specify this via the ``endpoint_override`` configuration option of
   that service group, in the Bare Metal service's configuration file.
   Taking the previous Networking service example, this would be

   .. code-block:: ini

      [neutron]
      ...
      endpoint_override = <NEUTRON_API_ADDRESS>

   (Replace `<NEUTRON_API_ADDRESS>` with actual address of a specific
   Networking service endpoint.)

#. Configure enabled drivers and hardware types as described in
   :doc:`/install/enabling-drivers`.

   A. If you enabled any driver that uses :ref:`direct-deploy`,
      Swift backend for the Image service must be installed and configured,
      see :ref:`image-store`.
      Ceph Object Gateway (RADOS Gateway) is also supported as the Image
      service's backend, see :ref:`radosgw support`.

#. Configure the network for ironic-conductor service to perform node
   cleaning, see :ref:`cleaning` from the admin guide.

#. Restart the ironic-conductor service:

   RHEL/CentOS/SUSE::

       sudo systemctl restart openstack-ironic-conductor

   Ubuntu/Debian::

       sudo service ironic-conductor restart

.. _Keystoneauth documentation: https://docs.openstack.org/keystoneauth/latest/
