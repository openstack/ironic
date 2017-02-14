Configuring ironic-conductor service
------------------------------------

#. Replace ``HOST_IP`` with IP of the conductor host, and replace ``DRIVERS``
   with a comma-separated list of drivers you chose for the conductor service
   as follows:

   .. code-block:: ini

      [DEFAULT]

      # IP address of this host. If unset, will determine the IP
      # programmatically. If unable to do so, will use "127.0.0.1".
      # (string value)
      my_ip=HOST_IP

      # Specify the list of drivers to load during service
      # initialization. Missing drivers, or drivers which fail to
      # initialize, will prevent the conductor service from
      # starting. The option default is a recommended set of
      # production-oriented drivers. A complete list of drivers
      # present on your system may be found by enumerating the
      # "ironic.drivers" entrypoint. An example may be found in the
      # developer documentation online. (list value)
      enabled_drivers=DRIVERS

   .. note::
      If a conductor host has multiple IPs, ``my_ip`` should
      be set to the IP which is on the same network as the bare metal nodes.

#. Configure the ironic-api service URL. Replace ``IRONIC_API_IP`` with IP of
   ironic-api service as follows:

   .. code-block:: ini

      [conductor]

      # URL of Ironic API service. If not set ironic can get the
      # current value from the keystone service catalog. (string
      # value)
      api_url=http://IRONIC_API_IP:6385

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

#. Configure the ironic-conductor service so that it can communicate with the
   Image service. Replace ``GLANCE_IP`` with the hostname or IP address of
   the Image service:

   .. code-block:: ini

      [glance]

      # Default glance hostname or IP address. (string value)
      glance_host=GLANCE_IP

   .. note::
      Swift backend for the Image service should be installed and configured
      for ``agent_*`` drivers. Starting with Mitaka the Bare Metal service also
      supports Ceph Object Gateway (RADOS Gateway) as the Image service's backend
      (`radosgw support <http://docs.openstack.org/developer/ironic/ocata/deploy/radosgw.html#radosgw-support>`_).

#. Set the URL (replace ``NEUTRON_IP``) for connecting to the Networking
   service, to be the Networking service endpoint:

   .. code-block:: ini

      [neutron]

      # URL for connecting to neutron. (string value)
      url=http://NEUTRON_IP:9696

   To configure the network for ironic-conductor service to perform node
   cleaning, see `CleaningNetworkSetup <http://docs.openstack.org/developer/ironic/ocata/deploy/cleaning.html>`_
   from the Ironic deploy guide.

#. Configure credentials for accessing other OpenStack services.

   In order to communicate with other OpenStack services, the Bare Metal
   service needs to use service users to authenticate to the OpenStack
   Identity service when making requests to other services.
   These users' credentials have to be configured in each
   configuration file section related to the corresponding service:

   * ``[neutron]`` - to access the OpenStack Networking service
   * ``[glance]`` - to access the OpenStack Image service
   * ``[swift]`` - to access the OpenStack Object Storage service
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
   together with ``Authentication plugin`` and ``Session`` concepts
   provided by it to instantiate service clients.
   Please refer to `Keystoneauth documentation`_ for supported plugins,
   their available options as well as Session-related options
   for authentication and connection respectively.

   In the example below, authentication information for user to access the
   OpenStack Networking service is configured to use:

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

#. Make sure that ``qemu-img`` and ``iscsiadm`` (in the case of using iscsi-deploy driver)
   binaries are installed and prepare the host system as described at
   `Setup the drivers for the Bare Metal service <http://docs.openstack.org/developer/ironic/ocata/deploy/install-guide.html#setup-the-drivers-for-the-bare-metal-service>`_

#. Restart the ironic-conductor service:

   .. TODO(mmitchell): Split this based on operating system
   .. code-block:: console

      Fedora/RHEL7/CentOS7:
        sudo systemctl restart openstack-ironic-conductor

      Ubuntu:
        sudo service ironic-conductor restart


.. _Keystoneauth documentation: http://docs.openstack.org/developer/keystoneauth/
