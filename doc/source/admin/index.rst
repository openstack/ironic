Administrator's Guide
=====================

Installation & Operations
-------------------------

If you are a system administrator running Ironic, this section contains
information that should help you understand how to deploy, operate, and upgrade
the services.

.. toctree::
  :maxdepth: 1

  Installation Guide </install/index>
  gmr
  Upgrade Guide <upgrade-guide>
  Release Notes <http://docs.openstack.org/releasenotes/ironic/>
  Troubleshooting FAQ <troubleshooting>

Configuration
-------------

There are many aspects of the Bare Metal service which are environment
specific. The following pages will be helpful in configuring specific aspects
of ironic that may or may not be suitable to every situation.

.. toctree::
  :maxdepth: 1

  Guide to Node Cleaning <cleaning>
  Configuring Node Inspection <inspection>
  Configuring RAID during deployment <raid>
  Security considerations for your Bare Metal installation <security>
  Adopting Nodes in an ACTIVE state <adoption>
  Configuring for Multi-tenant Networking <multitenancy>
  Configuring for port groups <portgroups>
  Configuring node web or serial console <console>
  Emitting software metrics <metrics>
  Auditing API Traffic <api-audit-support>
  Notifications <notifications>
  Ceph Object Gateway support <radosgw>
  /configuration/sample-config
  /configuration/sample-policy

Dashboard Integration
---------------------

A plugin for the OpenStack Dashboard (horizon) service is under development.
Documentation for that can be found within the ironic-ui project.

.. toctree::
  :maxdepth: 1

  Dashboard (horizon) plugin <http://docs.openstack.org/developer/ironic-ui/>
