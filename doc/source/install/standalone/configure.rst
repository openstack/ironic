Configuration
=============

This guide covers manual configuration of the Bare Metal service in the
standalone mode. Alternatively, Bifrost_ can be used for automatic
configuration.

.. _Bifrost: https://docs.openstack.org/bifrost/latest/

Service settings
----------------

It is possible to use the Bare Metal service without other OpenStack services.
You should make the following changes to ``/etc/ironic/ironic.conf``:

#. Choose an authentication strategy which supports standalone, one option is
   ``noauth``:

   .. code-block:: ini

    [DEFAULT]
    auth_strategy=noauth

   Another option is ``http_basic`` where the credentials are stored in an
   `Apache htpasswd format`_ file:

   .. code-block:: ini

    [DEFAULT]
    auth_strategy=http_basic
    http_basic_auth_user_file=/etc/ironic/htpasswd

   Only the ``bcrypt`` format is supported, and the Apache `htpasswd` utility can
   be used to populate the file with entries, for example:

   .. code-block:: shell

    htpasswd -nbB myName myPassword >> /etc/ironic/htpasswd

#. If you want to disable the Networking service, you should have your network
   pre-configured to serve DHCP and TFTP for machines that you're deploying.
   To disable it, change the following lines:

   .. code-block:: ini

    [dhcp]
    dhcp_provider=none

   .. note::
      If you disabled the Networking service and the driver that you use is
      supported by at most one conductor, PXE boot will still work for your
      nodes without any manual config editing. This is because you know all
      the DHCP options that will be used for deployment and can set up your
      DHCP server appropriately.

      If you have multiple conductors per driver, it would be better to use
      Networking since it will do all the dynamically changing configurations
      for you.

#. If you want to disable using a messaging broker between conductor and API
   processes, switch to JSON RPC instead:

   .. code-block:: ini

      [DEFAULT]
      rpc_transport = json-rpc

   JSON RPC also has its own authentication strategy. If it is not specified then
   the stategy defaults to ``[DEFAULT]``  ``auth_strategy``. The following will
   set JSON RPC to ``noauth``:

   .. code-block:: ini

    [json_rpc]
    auth_strategy = noauth

   For ``http_basic`` the conductor server needs a credentials file to validate
   requests:

   .. code-block:: ini

    [json_rpc]
    auth_strategy = http_basic
    http_basic_auth_user_file = /etc/ironic/htpasswd-json-rpc

   The API server also needs client-side credentials to be specified:

   .. code-block:: ini

    [json_rpc]
    auth_type = http_basic
    username = myName
    password = myPassword

Using CLI
---------

To use the
:python-ironicclient-doc:`baremetal CLI <cli/osc_plugin_cli.html>`,
set up these environment variables. If the ``noauth`` authentication strategy is
being used, the value ``none`` must be set for OS_AUTH_TYPE. OS_ENDPOINT is
the URL of the ironic-api process.
For example:

.. code-block:: shell

 export OS_AUTH_TYPE=none
 export OS_ENDPOINT=http://localhost:6385/

If the ``http_basic`` authentication strategy is being used, the value
``http_basic`` must be set for OS_AUTH_TYPE. For example:

.. code-block:: shell

 export OS_AUTH_TYPE=http_basic
 export OS_ENDPOINT=http://localhost:6385/
 export OS_USERNAME=myUser
 export OS_PASSWORD=myPassword

.. _`Apache htpasswd format`: https://httpd.apache.org/docs/current/misc/password_encryptions.html
