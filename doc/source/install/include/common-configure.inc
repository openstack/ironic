The Bare Metal service is configured via its configuration file. This file
is typically located at ``/etc/ironic/ironic.conf``.

Although some configuration options are mentioned here, it is recommended that
you review all the :doc:`/configuration/sample-config`
so that the Bare Metal service is configured for your needs.

It is possible to set up an ironic-api and an ironic-conductor services on the
same host or different hosts. Users also can add new ironic-conductor hosts
to deal with an increasing number of bare metal nodes. But the additional
ironic-conductor services should be at the same version as that of existing
ironic-conductor services.
