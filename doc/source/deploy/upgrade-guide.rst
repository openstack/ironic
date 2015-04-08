.. _upgrade-guide:

=====================================
Bare Metal Service Upgrade Guide
=====================================

This document outlines various steps and notes for operators to consider when
upgrading their Ironic-driven clouds from previous versions of OpenStack.

The Ironic service is tightly coupled with the Ironic driver that is shipped
with Nova. Currently, some special considerations must be taken into account
when upgrading your cloud from previous versions of OpenStack.

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
- Edit nova.conf and set force_config_drive to your liking, restaring
  nova-compute if necessary.

Note that during the period between Nova's upgrade and Ironic's upgrades,
instances can still be provisioned to nodes, however, any attempt by users
to specify a config drive for an instance will cause error until Ironic's
upgrade has completed.
