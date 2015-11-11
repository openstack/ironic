.. _radosgw support:

===========================
Ceph Object Gateway support
===========================

Overview
========
Ceph project is a powerful distributed storage system. It contains object store
and provides a RADOS Gateway Swift API which is compatible with OpenStack Swift
API. These two APIs use different formats for their temporary URLs.

Ironic added support for RADOS Gateway temporary URL in the Mitaka release.

Configure Ironic and Glance with RADOS Gateway
==============================================

#. Install Ceph storage with RADOS Gateway. See `Ceph documentation <http://docs.ceph.com/docs>`_.

#. Create RADOS Gateway credentials for Glance by executing the following
   commands on the RADOS Gateway admin host::

    sudo radosgw-admin user create --uid="GLANCE_USERNAME" --display-name="User for Glance"

    sudo radosgw-admin subuser create --uid=GLANCE_USERNAME --subuser=GLANCE_USERNAME:swift --access=full

    sudo radosgw-admin key create --subuser=GLANCE_USERNAME:swift --key-type=swift --secret=STORE_KEY

    sudo radosgw-admin user modify --uid=GLANCE_USERNAME --temp-url-key=TEMP_URL_KEY

   Replace GLANCE_USERNAME with a user name for Glance access, and replace
   STORE_KEY and TEMP_URL_KEY with suitable keys.

   Note: Do not use "--gen-secret" CLI parameter because it will cause the
   "radosgw-admin" utility to generate keys with slash symbols which do not
   work with Glance.

#. Configure Glance API service for RADOS Swift API as backend. Edit the
   configuration file for the Glance API service (is typically located at
   ``/etc/glance/glance-api.conf``). Replace RADOS_IP and PORT with the IP/port
   of the RADOS Gateway API service::

    [glance_store]

    stores = file, http, swift
    default_store = swift
    swift_store_auth_version = 1
    swift_store_auth_address = http://RADOS_IP:PORT/auth/1.0
    swift_store_user = GLANCE_USERNAME:swift
    swift_store_key = STORE_KEY
    swift_store_container = glance
    swift_store_create_container_on_put = True

   Note: RADOS Gateway uses FastCGI protocol for interacting with HTTP server.
   Read your HTTP server documentation if you want to enable HTTPS support.

#. Restart Glance API service and upload all needed images.

#. Change Ironic configuration file on the conductor host(s) as follows::

    [glance]

    swift_container = glance
    swift_api_version = v1
    swift_endpoint_url = http://RADOS_IP:PORT
    swift_temp_url_key = TEMP_URL_KEY
    temp_url_endpoint_type=radosgw

#. Restart Ironic conductor service(s).
