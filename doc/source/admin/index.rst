Administrator's Guide
=====================

If you are a system administrator running Ironic, this section contains
information that may help you understand how to operate and upgrade
the services.

.. toctree::
  :maxdepth: 1

   Ironic Python Agent <drivers/ipa>
   Node Hardware Inspection <inspection>
   Node Deployment <node-deployment>
   Node Cleaning <cleaning>
   Node Adoption <adoption>
   Node Retirement <retirement>
   RAID Configuration <raid>
   BIOS Settings <bios>
   Node Rescuing <rescue>
   Configuring to boot from volume <boot-from-volume>
   Multi-tenant Networking <multitenancy>
   Port Groups <portgroups>
   Configuring Web or Serial Console <console>
   Enabling Notifications <notifications>
   Conductor Groups <conductor-groups>
   Upgrade Guide <upgrade-guide>
   Security <security>
   Troubleshooting FAQ <troubleshooting>
   Power Sync with the Compute Service <power-sync>
   Node Multi-Tenancy <node-multitenancy>
   Fast-Track Deployment <fast-track>
   Booting a Ramdisk or an ISO <ramdisk-boot>

Drivers, Hardware Types and Hardware Interfaces
-----------------------------------------------

.. toctree::
  :maxdepth: 3

  drivers

Advanced Topics
---------------

.. toctree::
  :maxdepth: 1

   Ceph Object Gateway <radosgw>
   Windows Images <building-windows-images>
   Emitting Software Metrics <metrics>
   Auditing API Traffic <api-audit-support>
   Service State Reporting <gmr>
   Agent Token <agent-token>
   Deploying without BMC Credentials <agent-power>
   Layer 3 or DHCP-less Ramdisk Booting <dhcp-less>
   Tuning Ironic <tuning>
   Role Based Access Control <secure-rbac>

.. toctree::
  :hidden:

  deploy-steps

Dashboard Integration
---------------------

A plugin for the OpenStack Dashboard (horizon) service is under development.
Documentation for that can be found within the ironic-ui project.

* :ironic-ui-doc:`Dashboard (horizon) plugin <>`
