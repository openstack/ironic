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

.. note::
   The default value of ``image_server_auth_strategy`` is ``noauth``.
   When the default is in effect, no credentials are configured or
   sent, and none of the options described in this document have any
   effect. The considerations below only apply to operators who have
   explicitly set ``image_server_auth_strategy`` to ``http_basic``.

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

Restricting credential scope
----------------------------

When ``image_server_auth_strategy`` is explicitly set to ``http_basic``,
Ironic will send the configured credentials to **every** host from which
images are requested. This means that if a user supplies an image URL
pointing to a host the operator does not control, the operator's image
server credentials will be sent to that host.

.. important::
   This only applies when the operator has explicitly changed
   ``image_server_auth_strategy`` from its default value of ``noauth``
   to ``http_basic``. Deployments using the default ``noauth`` strategy
   do not send any credentials and are not affected.

To mitigate this, operators may configure ``image_server_auth_hosts`` with a
list of trusted hostnames or domain suffixes. When this option is configured,
credentials will only be sent to hosts matching an entry in the list.
Requests to hosts not in the list will proceed without credentials.

Entries may be exact hostnames (e.g. ``images.example.com``) or domain
suffixes prefixed with a dot (e.g. ``.example.com``). A suffix entry matches
any hostname under that domain, so ``.example.com`` matches
``images.example.com`` and ``backup.example.com`` but does not match the
bare ``example.com``.

This filtering is applied both when the conductor itself retrieves images
and when determining whether to supply credentials to the
ironic-python-agent for image downloads.

.. code-block:: ini

  [deploy]
  ...
  image_server_auth_strategy = http_basic
  image_server_user = username
  image_server_password = password
  image_server_auth_hosts = images.example.com,.internal
  ...

.. note::
   In this release, ``image_server_auth_permit_unknown_hosts`` defaults
   to ``True``. When ``image_server_auth_hosts`` is not configured,
   credentials are therefore still sent to every host, preserving the
   prior behavior. To restrict credentials in this release, either
   configure ``image_server_auth_hosts`` or set
   ``image_server_auth_permit_unknown_hosts`` to ``False``. The default
   of ``image_server_auth_permit_unknown_hosts`` will change to
   ``False`` in the 2026.2 release, after which credentials are not sent
   to any host unless ``image_server_auth_hosts`` is configured.

.. note::
   Only the hostname is considered when matching entries; the port is
   ignored. An entry of ``images.example.com`` therefore matches
   ``images.example.com`` regardless of the port used in the image URL.

.. note::
   Each Ironic conductor operates an HTTP server for serving boot
   artifacts and locally cached images to nodes. This endpoint,
   configured via ``[deploy]http_url``, is designed to support
   unauthenticated access and does not require image server
   credentials. Operators should not include the conductor's own
   HTTP server hostname in the ``image_server_auth_hosts`` list
   as it serves no purpose in that context.

Known limitations
-----------------

This implementation of the authentication strategy for user image handling is
implemented via the global Ironic configuration thus it doesn't provide node
specific customization options.

When ``image_server_auth_strategy`` is set to ``http_basic`` and
``image_server_auth_hosts`` is not configured, all image sources will be
treated with the same authentication strategy and Ironic will use the same
credentials against all sources. Operators who have configured
``http_basic`` authentication are encouraged to configure
``image_server_auth_hosts`` to restrict which hosts receive credentials.

.. note::
   The default value of ``image_server_auth_permit_unknown_hosts`` will
   change from ``True`` to ``False`` in the 2026.2 release. After that
   change, operators who have configured ``http_basic`` authentication
   must also explicitly configure ``image_server_auth_hosts`` for
   credentials to be sent. Operators are encouraged to configure
   ``image_server_auth_hosts`` before the 2026.2 release.
