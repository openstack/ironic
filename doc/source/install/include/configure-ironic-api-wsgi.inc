Configuring ironic-api behind a WSGI server
--------------------------------------------

Bare Metal service can be configured to run behind any WSGI-capable
web server like uWSGI or Gunicorn for better performance and scalability.

.. note::
   This is optional, the ironic APIs can be run using
   the standalone ``ironic-api`` command. However, for production deployments,
   it is recommended to use a proper WSGI server for better performance,
   multiple workers, and integration with existing infrastructure.

The WSGI application
~~~~~~~~~~~~~~~~~~~~

Ironic provides a WSGI application at ``ironic.wsgi:application`` that can
be used with any WSGI server. The below example uses uWSGI, which is used in
Ironic CI jobs.

Using uWSGI
~~~~~~~~~~~

#. Install uWSGI::

       pip install uwsgi

#. Create a uWSGI configuration file (e.g., ``/etc/uwsgi/ironic.ini``)::

       [uwsgi]
       module = ironic.wsgi:application
       http-socket = 127.0.0.1:6385
       processes = 2
       ; allow 60 seconds for graceful shutdown on SIGTERM
       die-on-term = true
       exit-on-reload = false
       hook-master-start = unix_signal:15 gracefully_kill_them_all
       worker-reload-mercy = 60
       ; disallow connection reuse
       add-header = Connection: close
       ; Prevent thundering herd on accept()
       thunder-lock = true
       ; ensure file descriptors aren't shared between processes
       lazy-apps = true
       enable-threads = true
       master = true

.. note::
   This uWSGI configuration and comments are based on devstack configuration.
   You may need to modify settings depending on your deployment method and
   scale.


#. Start uWSGI::

       uwsgi --ini /etc/uwsgi/ironic.ini

Reverse Proxy Configuration
~~~~~~~~~~~~~~~~~~~~~~~~~~~~

WSGI servers are typically deployed behind a reverse proxy like nginx or
Apache for SSL termination, load balancing, and serving static files.

Example nginx configuration::

    upstream ironic-api {
        server 127.0.0.1:6385;
    }

    server {
        listen 443 ssl;
        server_name ironic.example.com;

        ssl_certificate /etc/ssl/certs/ironic.crt;
        ssl_certificate_key /etc/ssl/private/ironic.key;

        location / {
            proxy_pass http://ironic-api;
            proxy_set_header Host $host;
            proxy_set_header X-Real-IP $remote_addr;
            proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
            proxy_set_header X-Forwarded-Proto $scheme;
        }
    }

For detailed reverse proxy configurations, see:

* `nginx documentation <https://docs.nginx.com/nginx/admin-guide/web-server/reverse-proxy/>`_
* `Apache mod_proxy documentation <https://httpd.apache.org/docs/current/mod/mod_proxy.html>`_
* `HAProxy documentation <https://www.haproxy.org/download/2.4/doc/configuration.txt>`_

Passing Configuration Options
------------------------------

By default, Ironic will use its standard configuration file search paths.
If you need to specify a custom configuration file:

For the initialization method with arguments::

    # uWSGI with custom config (in ini file)
    [uwsgi]
    module = ironic.api.wsgi:initialize_wsgi_app(argv=["--config-file=/etc/ironic/ironic.conf"])

Alternatively, you can set environment variables before starting the WSGI server::

    export OS_CLOUD=mycloud
    # or
    export IRONIC_CONF=/etc/ironic/ironic.conf

Important Considerations
~~~~~~~~~~~~~~~~~~~~~~~~

#. Stop and disable the standalone ironic-api service before starting
   the WSGI server to avoid port conflicts.

#. When behind a reverse proxy, ensure ``[oslo_middleware]/enable_proxy_headers_parsing``
   is set to ``True`` in ironic.conf to properly handle X-Forwarded headers.
