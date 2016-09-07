Configuring ironic-api behind mod_wsgi
--------------------------------------

Bare Metal service comes with an example file for configuring the
``ironic-api`` service to run behind Apache with mod_wsgi.

#. Install the apache service:

   .. TODO(mmitchell): Split this based on operating system
   .. code-block:: console

      Fedora 21/RHEL7/CentOS7:
        sudo yum install httpd

      Fedora 22 (or higher):
        sudo dnf install httpd

      Debian/Ubuntu:
        apt-get install apache2


#. Copy the ``etc/apache2/ironic`` file under the apache sites:

   .. TODO(mmitchell): Split this based on operating system
   .. code-block:: console

      Fedora/RHEL7/CentOS7:
        sudo cp etc/apache2/ironic /etc/httpd/conf.d/ironic.conf

      Debian/Ubuntu:
        sudo cp etc/apache2/ironic /etc/apache2/sites-available/ironic.conf


#. Edit the recently copied ``<apache-configuration-dir>/ironic.conf``:

   #. Modify the ``WSGIDaemonProcess``, ``APACHE_RUN_USER`` and
      ``APACHE_RUN_GROUP`` directives to set the user and group values to
      an appropriate user on your server.

   #. Modify the ``WSGIScriptAlias`` directive to point to the
      ``ironic/api/app.wsgi`` script.

   #. Modify the ``Directory`` directive to set the path to the Ironic API code.

   #. Modify the ``ErrorLog`` and ``CustomLog`` to redirect the logs
      to the right directory (on Red Hat systems this is usually under
      /var/log/httpd).

#. Enable the apache ``ironic`` in site and reload:

   .. TODO(mmitchell): Split this based on operating system
   .. code-block:: console

      Fedora/RHEL7/CentOS7:
        sudo systemctl reload httpd

      Debian/Ubuntu:
        sudo a2ensite ironic
        sudo service apache2 reload

.. note::
   The file ``ironic/api/app.wsgi`` is installed with the rest of the Bare Metal
   service application code, and should not need to be modified.
