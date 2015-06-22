.. _upgrade-guide:

=====================================
Bare Metal Service Upgrade Guide
=====================================

This document outlines various steps and notes for operators to consider when
upgrading their Ironic-driven clouds from previous versions of OpenStack.

The Ironic service is tightly coupled with the Ironic driver that is shipped
with Nova. Currently, some special considerations must be taken into account
when upgrading your cloud from previous versions of OpenStack.

Upgrading from Kilo to Liberty
==============================

Inspection
----------

If you used in-band inspection with **ironic-discoverd**, you have to install
**python-ironic-inspector-client** before the upgrade. It's also recommended
that you switch to using **ironic-inspector**, which is a newer version of the
same service.

Upgrading from Juno to Kilo
===========================

When upgrading a cloud from Juno to Kilo, users must ensure the Nova
service is upgraded prior to upgrading the Ironic service. Additionally,
users need to set a special config flag in Nova prior to upgrading to ensure
the newer version of Nova is not attempting to take advantage of new Ironic
features until the Ironic service has been upgraded. The steps for upgrading
your Nova and Ironic services are as follows:

- Edit nova.conf and ensure force_config_drive=False is set in the [DEFAULT]
  group. Restart nova-compute if necessary.
- Install new Nova code, run database migrations
- Install new python-ironicclient code.
- Restart Nova services.
- Install new Ironic code, run database migrations, restart Ironic services.
- Edit nova.conf and set force_config_drive to your liking, restarting
  nova-compute if necessary.

Note that during the period between Nova's upgrade and Ironic's upgrades,
instances can still be provisioned to nodes, however, any attempt by users
to specify a config drive for an instance will cause error until Ironic's
upgrade has completed.

Cleaning
--------
A new feature in Kilo is support for the cleaning of nodes between workloads to
ensure the node is ready for another workload. This can include erasing the
hard drives, updating firmware, and other steps. For more information, see
:ref:`cleaning`.

If Ironic is configured with cleaning enabled (defaults to True) and to use
Neutron as the DHCP provider (also the default), you will need to set the
`cleaning_network_uuid` option in the Ironic configuration file before starting
the Kilo Ironic service. See :ref:`CleaningNetworkSetup` for information on
how to set up the cleaning network for Ironic.
