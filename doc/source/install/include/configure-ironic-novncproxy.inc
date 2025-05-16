Configuring ironic-novncproxy service
-------------------------------------

#. The NoVNC proxy service needs to look up nodes in the database, so
   ``ironic-novncproxy`` requires the same database configuration as
   ``ironic-api`` and ``ironic-conductor``.

   Configure the location of the database via the ``connection`` option. In the
   following, replace ``IRONIC_DBPASSWORD`` with the password of your
   ``ironic`` user, and replace ``DB_IP`` with the IP address where the DB
   server is located:

   .. code-block:: ini

      [database]

      # The SQLAlchemy connection string used to connect to the
      # database (string value)
      connection=mysql+pymysql://ironic:IRONIC_DBPASSWORD@DB_IP/ironic?charset=utf8

#. Configure NoVNC and host graphical console options. Replace ``PUBLIC_IP`` and
   ``PUBLIC_URL`` with appropriate values:

   .. code-block:: ini

      [vnc]

      # Enable VNC related features, required to allow the ironic-novncproxy service to start
      enabled=True

      # Port to bind to for serving NoVNC web assets and websockets
      port=6090

      # IP address to bind to for serving NoVNC web assets and websockets
      host_ip=PUBLIC_IP

#. Restart the ironic-novncproxy service:

   RHEL/CentOS::

       sudo systemctl restart openstack-ironic-novncproxy

   Ubuntu/Debian::

       sudo service ironic-novncproxy restart
