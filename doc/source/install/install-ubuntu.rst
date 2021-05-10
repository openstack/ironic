.. _install-ubuntu:

================================
Install and configure for Ubuntu
================================

This section describes how to install and configure the Bare Metal
service for Ubuntu 14.04 (LTS).

.. include:: include/common-prerequisites.inc

Install and configure components
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

#. Install from packages (using apt-get)

   .. code-block:: console

      # apt-get install ironic-api ironic-conductor python3-ironicclient

#. Enable services

   Services are enabled by default on Ubuntu.

.. include:: include/common-configure.inc

.. include:: include/configure-ironic-api.inc

.. include:: include/configure-ironic-api-mod_wsgi.inc

.. include:: include/configure-ironic-conductor.inc
