======================================================
HTTP(s) Authentication strategy for user image servers
======================================================

How to enable the feature via global configuration options
----------------------------------------------------------

There are 3 variables that could be used to manage image server
authentication strategy. The 3 variables are structured such a way that 1 of
them ``image_server_auth_strategy`` (string) provides the option to specify
the desired authentication strategy. Currently the only supported
authentication strategy is ``http_basic`` that represents the HTTP(S) Basic
Authentication also known as the ``RFC 7616`` internet standard.

The other two variables ``image_server_password`` and ``image_server_user``
provide username and password credentials for any authentication strategy
that requires username and credentials to enable the authentication during
image download processes. ``image_server_auth_strategy`` not just enables the
feature but enforces checks on the values of the 2 related credentials.
Currently only the ``http_basic`` strategy is utilizing the
``image_server_password`` and ``image_server_user`` variables.

When a authentication strategy is selected against the user image server an
exception will be raised in case any of the credentials are None or an empty
string. The variables belong to the ``deploy`` configuration group and could be
configured via the global Ironic configuration file.

The authentication strategy configuration affects the download process
for images downloaded by the conductor or the ironic-python-agent.

Example
-------

Example of activating the ``http-basic`` strategy via
``/etc/ironic/ironic.conf``:

.. code-block:: ini

  [deploy]
  ...
  image_server_auth_strategy = http_basic
  image_server_user = username
  image_server_password = password
  ...

Known limitations
-----------------

This implementation of the authentication strategy for user image handling is
implemented via the global Ironic configuration thus it doesn't provide node
specific customization options.

When ``image_server_auth_strategy`` is set to any valid value all image
sources will be treated with the same authentication strategy and Ironic will
use the same credentials against all sources.

