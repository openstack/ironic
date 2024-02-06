PXE filter service
==================

The PXE filter service is responsible for managing the dnsmasq instance
that is responsible for :ref:`unmanaged-inspection`. Running it allows
this dnsmasq instance to co-exist with the OpenStack Networking service's DHCP
server on the same physical network.

.. warning::
   The PXE filter service is currently experimental. For a production grade
   solution, please stay with ironic-inspector for the time being.

How it works?
-------------

At the core of the PXE filter service is a periodic task that fetches all ports
and compares the node ID's with the ID's of the nodes undergoing in-band
inspection. All of the MAC addresses are added to the dnsmasq host files:
to the allowlist of nodes on inspection and to the denylist for the rest.

Additionally, when any nodes are on inspection, unknown MACs are also allowed.
Otherwise, access from unknown MACs to the dnsmasq service is denied.

Installation
------------

Start with :ref:`configure-unmanaged-inspection`. Then create a *hostsdir*
writable by the PXE filter service and readable by dnsmasq. Configure it in the
dnsmasq configuration file

.. code-block:: ini

   dhcp-hostsdir=/var/lib/ironic/hostsdir

and in the Bare Metal service configuration

.. code-block:: ini

   [pxe_filter]
   dhcp_hostsdir = /var/lib/ironic/hostsdir

Then create a systemd service to start ``ironic-pxe-filter`` alongside dnsmasq,
e.g.

.. code-block:: ini

   [Unit]
   Description=Ironic PXE filter

   [Service]
   Type=notify
   Restart=on-failure
   ExecStart=/usr/bin/ironic-pxe-filter --config-file /etc/ironic/ironic.conf
   User=ironic
   Group=ironic

Note that because of technical limitations, the PXE filter process cannot clean
up the *hostsdir* itself. You may want to do it on the service start-up, e.g.
like this (assuming the dnsmasq service is ``ironic-dnsmasq`` and its PID is
stored in ``/run/ironic/dnsmasq.pid``):

.. code-block:: ini

   [Unit]
   Description=Ironic PXE filter
   Requires=ironic-dnsmasq.service
   After=ironic-dnsmasq.service

   [Service]
   Type=notify
   Restart=on-failure
   ExecStartPre=+/bin/bash -c "rm -f /usr/lib/ironic/hostsdir/* && kill -HUP $(cat /run/ironic/dnsmasq.pid) || true"
   ExecStart=/usr/bin/ironic-pxe-filter --config-file /etc/ironic/ironic.conf
   User=ironic
   Group=ironic

Scale considerations
--------------------

The PXE filter service should be run once per each dnsmasq instance dedicated
to unmanaged inspection. In most clouds, that will be 1 instance.
