.. _install-obs:

============================================================
Install and configure for openSUSE and SUSE Linux Enterprise
============================================================

This section describes how to install and configure the Bare Metal service
for openSUSE Leap 42.2 and SUSE Linux Enterprise Server 12 SP2.

.. note::
   Installation of the Bare Metal service on openSUSE and SUSE Linux Enterprise
   Server is not officially supported. Nevertheless, installation should be
   possible.

.. include:: include/common-prerequisites.rst

Install and configure components
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

#. Install from packages

   .. code-block:: console

      # zypper install openstack-ironic-api openstack-ironic-conductor python-ironicclient

#. Enable services

   .. code-block:: console

      # systemctl enable openstack-ironic-api openstack-ironic-conductor
      # systemctl start openstack-ironic-api openstack-ironic-conductor

.. include:: include/common-configure.rst

.. include:: include/configure-ironic-api.rst

.. include:: include/configure-ironic-api-mod_wsgi.rst

.. include:: include/configure-ironic-conductor.rst
