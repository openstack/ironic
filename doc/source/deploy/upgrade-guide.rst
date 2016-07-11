.. _upgrade-guide:

================================
Bare Metal Service Upgrade Guide
================================

This document outlines various steps and notes for operators to consider when
upgrading their Ironic-driven clouds from previous versions of OpenStack.

The Ironic service is tightly coupled with the Ironic driver that is shipped
with Nova. Currently, some special considerations must be taken into account
when upgrading your cloud from previous versions of OpenStack.

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
for details on which Ironic versions can work with which
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
instances can still be provisioned to nodes. However, any attempt by users to
specify a config drive for an instance will cause an error until Ironic's
upgrade has completed.

Cleaning
--------
A new feature in Kilo is support for the automated cleaning of nodes between
workloads to ensure the node is ready for another workload. This can include
erasing the hard drives, updating firmware, and other steps. For more
information, see :ref:`automated_cleaning`.

If Ironic is configured with automated cleaning enabled (defaults to True) and
to use Neutron as the DHCP provider (also the default), you will need to set the
`cleaning_network_uuid` option in the Ironic configuration file before starting
the Kilo Ironic service. See :ref:`CleaningNetworkSetup` for information on
how to set up the cleaning network for Ironic.
