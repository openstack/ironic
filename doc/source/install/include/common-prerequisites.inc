Install and configure prerequisites
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

The Bare Metal service is a collection of components that provides support to
manage and provision physical machines. You can configure these components to
run on separate nodes or the same node. In this guide, the components run on
one node, typically the Compute Service's compute node.

It assumes that the Identity, Image, Compute, and Networking services
have already been set up.


Set up the database for Bare Metal
----------------------------------

The Bare Metal service stores information in a database. This guide uses the
MySQL database that is used by other OpenStack services.

#. In MySQL, create an ``ironic`` database that is accessible by the
   ``ironic`` user. Replace ``IRONIC_DBPASSWORD`` with a suitable password:

   .. code-block:: console

      # mysql -u root -p
      mysql> CREATE DATABASE ironic CHARACTER SET utf8mb3;
      mysql> GRANT ALL PRIVILEGES ON ironic.* TO 'ironic'@'localhost' \
             IDENTIFIED BY 'IRONIC_DBPASSWORD';
      mysql> GRANT ALL PRIVILEGES ON ironic.* TO 'ironic'@'%' \
             IDENTIFIED BY 'IRONIC_DBPASSWORD';

.. note::
   When creating the database to house Ironic, specifically on MySQL/MariaDB,
   the character set *cannot* be 4 byte Unicode characters. This is due to
   an internal structural constraint. UTF8, in these database platforms,
   has traditionally meant ``utf8mb3``, short for "UTF-8, 3 byte encoding",
   however the platforms are expected to move to ``utf8mb4`` which is
   incompatible with Ironic.
