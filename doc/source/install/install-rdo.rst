.. _install-rdo:

=============================================================
Install and configure for Red Hat Enterprise Linux and CentOS
=============================================================


This section describes how to install and configure the Bare Metal service
for Red Hat Enterprise Linux 7 and CentOS 7.

.. include:: include/common-prerequisites.inc

Install and configure components
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

#. Install from packages

   - Using ``dnf``

     .. code-block:: console

        # dnf install openstack-ironic-api openstack-ironic-conductor python-ironicclient

   - Using ``yum``

     .. code-block:: console

        # yum install openstack-ironic-api openstack-ironic-conductor python-ironicclient

#. Enable services

   .. code-block:: console

      # systemctl enable openstack-ironic-api openstack-ironic-conductor
      # systemctl start openstack-ironic-api openstack-ironic-conductor

.. include:: include/common-configure.inc

.. include:: include/configure-ironic-api.inc

.. include:: include/configure-ironic-api-mod_wsgi.inc

.. include:: include/configure-ironic-conductor.inc
