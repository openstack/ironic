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
   setting one or more of these options. Ironic-conductor should use the same
   configuration as ironic-api. Replace ``RABBIT_HOST`` with the address of the
   RabbitMQ server:

   .. code-block:: ini

      [DEFAULT]

      # The messaging driver to use, defaults to rabbit. Other
      # drivers include qpid and zmq. (string value)
      #rpc_backend=rabbit

      [oslo_messaging_rabbit]

      # The RabbitMQ broker address where a single node is used.
      # (string value)
      rabbit_host=RABBIT_HOST

      # The RabbitMQ userid. (string value)
      #rabbit_userid=guest

      # The RabbitMQ password. (string value)
      #rabbit_password=guest

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
      (`radosgw support <http://docs.openstack.org/developer/ironic/newton/deploy/radosgw.html#radosgw-support>`_).

#. Set the URL (replace ``NEUTRON_IP``) for connecting to the Networking
   service, to be the Networking service endpoint:

   .. code-block:: ini

      [neutron]

      # URL for connecting to neutron. (string value)
      url=http://NEUTRON_IP:9696

   To configure the network for ironic-conductor service to perform node
   cleaning, see `CleaningNetworkSetup <http://docs.openstack.org/developer/ironic/newton/deploy/cleaning.html>`_
   from the Ironic deploy guide.

#. Configure the ironic-conductor service to use these credentials with the
   Identity service. Ironic-conductor should use the same configuration as
   ironic-api. Replace ``IDENTITY_IP`` with the IP of the Identity server,
   and replace ``IRONIC_PASSWORD`` with the password you chose for the
   ``ironic`` user in the Identity service:

   .. code-block:: ini

      [keystone_authtoken]

      # Complete public Identity API endpoint (string value)
      auth_uri=http://IDENTITY_IP:5000/

      # Complete admin Identity API endpoint. This should specify
      # the unversioned root endpoint e.g. https://localhost:35357/
      # (string value)
      identity_uri=http://IDENTITY_IP:35357/

      # Service username. (string value)
      admin_user=ironic

      # Service account password. (string value)
      admin_password=IRONIC_PASSWORD

      # Service tenant name. (string value)
      admin_tenant_name=service

#. Make sure that ``qemu-img`` and ``iscsiadm`` (in the case of using iscsi-deploy driver)
   binaries are installed and prepare the host system as described at
   `Setup the drivers for the Bare Metal service <http://docs.openstack.org/developer/ironic/newton/deploy/install-guide.html#setup-the-drivers-for-the-bare-metal-service>`_

#. Restart the ironic-conductor service:

   .. TODO(mmitchell): Split this based on operating system
   .. code-block:: console

      Fedora/RHEL7/CentOS7:
        sudo systemctl restart openstack-ironic-conductor

      Ubuntu:
        sudo service ironic-conductor restart
