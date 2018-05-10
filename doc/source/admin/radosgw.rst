.. _radosgw support:

===========================
Ceph Object Gateway support
===========================

Overview
========
Ceph project is a powerful distributed storage system. It contains object store
and provides a RADOS Gateway Swift API which is compatible with OpenStack Swift
API.

Ironic added support for RADOS Gateway temporary URL in the Mitaka release.

Configure Ironic and Glance with RADOS Gateway
==============================================

#. Install Ceph storage with RADOS Gateway. See `Ceph documentation <http://docs.ceph.com/docs>`_.

#. Configure RADOS Gateway to use keystone for authentication. See
   `Integrating with OpenStack Keystone <http://docs.ceph.com/docs/master/radosgw/keystone/>`_

#. Register RADOS Gateway endpoint in the keystone catalog, with the same
   format swift uses, as the ``object-store`` service. URL example:

   ``http://rados.example.com:8080/swift/v1/AUTH_$(project_id)s``.

   In the ceph configuration, make sure radosgw is configured with the
   following value::

     rgw swift account in url = True

#. Configure Glance API service for RADOS Swift API as backend. Edit the
   configuration file for the Glance API service (is typically located at
   ``/etc/glance/glance-api.conf``)::

    [glance_store]

    stores = file, http, swift
    default_store = swift
    default_swift_reference=ref1
    swift_store_config_file=/etc/glance/glance-swift-creds.conf
    swift_store_container = glance
    swift_store_create_container_on_put = True

   In the file referenced in ``swift_store_config_file`` option, add the
   following::

    [ref1]
    user = <service project>:<service user name>
    key = <service user password>
    user_domain_id = default
    project_domain_id = default
    auth_version = 3
    auth_address = http://keystone.example.com/identity

   Values for user and key options correspond to keystone credentials for
   RADOS Gateway service user.

   Note: RADOS Gateway uses FastCGI protocol for interacting with HTTP server.
   Read your HTTP server documentation if you want to enable HTTPS support.

#. Restart Glance API service and upload all needed images.

#. If you're using custom container name in RADOS, change Ironic configuration
   file on the conductor host(s) as follows::

    [glance]

    swift_container = glance

#. Restart Ironic conductor service(s).
