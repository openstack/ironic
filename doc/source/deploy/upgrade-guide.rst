.. _upgrade-guide:

================================
Bare Metal Service Upgrade Guide
================================

This document outlines various steps and notes for operators to consider when
upgrading their ironic-driven clouds from previous versions of OpenStack.

The ironic service is tightly coupled with the ironic driver that is shipped
with nova. Some special considerations must be taken into account
when upgrading your cloud from previous versions of OpenStack.

The `release notes <http://docs.openstack.org/releasenotes/ironic/>`_
should always be read carefully when upgrading the ironic service. Starting
with the Mitaka series, specific upgrade steps and considerations are
well-documented in the release notes. Specific upgrade considerations prior
to the Mitaka series are documented below.

Upgrades are only supported one series at a time, or within a series.

General upgrades - all versions
===============================

Starting with the Liberty release, the ironic service should always be upgraded
before the nova service. The ironic virt driver in nova always uses a specific
version of the ironic REST API. This API version may be one that was introduced
in the same development cycle, so upgrading nova first may result in nova being
unable to use ironic's API.

When upgrading ironic, the following steps should always be taken:

* Update ironic code, without restarting services yet.

* Run database migrations

* Restart ironic-conductor and ironic-api services.

Upgrading from Kilo to Liberty
==============================

In-band Inspection
------------------

If you used in-band inspection with **ironic-discoverd**, you have to install
**python-ironic-inspector-client** during the upgrade. This package contains a
client module for the in-band inspection service, which was previously part of
the **ironic-discoverd** package. Ironic Liberty supports the
**ironic-discoverd** service, but does not support its in-tree client module.
Please refer to
`ironic-inspector version support matrix
<http://docs.openstack.org/developer/ironic-inspector/install.html#version-support-matrix>`_
for details on which ironic versions can work with which
**ironic-inspector**/**ironic-discoverd** versions.

It's also highly recommended that you switch to using **ironic-inspector**,
which is a newer (and compatible on API level) version of the same service.

The discoverd to inspector upgrade procedure is as follows:

#. Install **ironic-inspector** on the machine where you have
   **ironic-discoverd** (usually the same as conductor).

#. (Recommended) update the **ironic-inspector** configuration file to stop
   using deprecated configuration options, as marked by the comments in the
   `example.conf
   <https://git.openstack.org/cgit/openstack/ironic-inspector/tree/example.conf>`_.

   The file name is provided on the command line when starting
   **ironic-discoverd**, and the previously recommended default was
   ``/etc/ironic-discoverd/discoverd.conf``. In this case, for the sake of
   consistency it's recommended you move the configuration file to
   ``/etc/ironic-inspector/inspector.conf``.

#. Shutdown **ironic-discoverd**, and start **ironic-inspector**.

#. During upgrade of each conductor instance:

    #. Shutdown the conductor
    #. Uninstall **ironic-discoverd**,
       install **python-ironic-inspector-client**
    #. Update the conductor Kilo -> Liberty
    #. (Recommended) update ``ironic.conf`` to use ``[inspector]`` section
       instead of ``[discoverd]`` (option names are the same)
    #. Start the conductor

Upgrading from Juno to Kilo
===========================

When upgrading a cloud from Juno to Kilo, users must ensure the nova
service is upgraded prior to upgrading the ironic service. Additionally,
users need to set a special config flag in nova prior to upgrading to ensure
the newer version of nova is not attempting to take advantage of new ironic
features until the ironic service has been upgraded. The steps for upgrading
your nova and ironic services are as follows:

- Edit nova.conf and ensure force_config_drive=False is set in the [DEFAULT]
  group. Restart nova-compute if necessary.
- Install new nova code, run database migrations
- Install new python-ironicclient code.
- Restart nova services.
- Install new ironic code, run database migrations, restart ironic services.
- Edit nova.conf and set force_config_drive to your liking, restarting
  nova-compute if necessary.

Note that during the period between nova's upgrade and ironic's upgrades,
instances can still be provisioned to nodes. However, any attempt by users to
specify a config drive for an instance will cause an error until ironic's
upgrade has completed.

Cleaning
--------
A new feature in Kilo is support for the automated cleaning of nodes between
workloads to ensure the node is ready for another workload. This can include
erasing the hard drives, updating firmware, and other steps. For more
information, see :ref:`automated_cleaning`.

If ironic is configured with automated cleaning enabled (defaults to True) and
to use Neutron as the DHCP provider (also the default), you will need to set the
`cleaning_network_uuid` option in the ironic configuration file before starting
the Kilo ironic service. See :ref:`CleaningNetworkSetup` for information on
how to set up the cleaning network for ironic.
