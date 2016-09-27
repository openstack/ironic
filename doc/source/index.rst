============================================
Welcome to Ironic's developer documentation!
============================================

Introduction
============

Ironic is an OpenStack project which provisions bare metal (as opposed to
virtual) machines. It may be used independently or as part of an OpenStack
Cloud, and integrates with the OpenStack Identity (keystone), Compute (nova),
Network (neutron), Image (glance), and Object (swift) services.

The Bare Metal service manages hardware through both common (eg. PXE and IPMI)
and vendor-specific remote management protocols. It provides the cloud operator
with a unified interface to a heterogeneous fleet of servers while also
providing the Compute service with an interface that allows physical servers to
be managed as though they were virtual machines.

`An introduction to ironic's conceptual architecture <deploy/user-guide.html>`_
is available for those new to the project.

Site Notes
----------

This site is primarily intended to provide documentation for developers
interested in contributing to or working with ironic. It *also* contains
references and guides for administrators which are not yet hosted elsewhere on
the OpenStack documentation sites.

This documentation is continually updated and may not represent the state of
the project at any specific prior release. To access documentation for a
previous release of ironic, append the OpenStack release name to the URL, for
example:

    http://docs.openstack.org/developer/ironic/mitaka/


Bare Metal API References
=========================

Ironic's REST API has changed since its first release, and continues to evolve
to meet the changing needs of the community.  Here we provide a conceptual
guide as well as more detailed reference documentation.

.. toctree::
  :maxdepth: 1

  API Concept Guide <dev/webapi>
  API Reference (latest) <http://developer.openstack.org/api-ref/baremetal/>
  API Version History <dev/webapi-version-history>


Developer's Guide
=================

Getting Started
---------------

If you are new to ironic, this section contains information that should help
you get started as a developer working on the project or contributing to the
project.

.. toctree::
  :maxdepth: 1

  Developer Contribution Guide <dev/code-contribution-guide>
  Setting Up Your Development Environment <dev/dev-quickstart>
  Frequently Asked Questions <dev/faq>

The following pages describe the architecture of the Bare Metal service
and may be helpful to anyone working on or with the service, but are written
primarily for developers.

.. toctree::
  :maxdepth: 1

  Ironic System Architecture <dev/architecture>
  Provisioning State Machine <dev/states>
  Notifications <dev/notifications>


Writing Drivers
---------------

Ironic's community includes many hardware vendors who contribute drivers that
enable more advanced functionality when Ironic is used in conjunction with that
hardware. To do this, the Ironic developer community is committed to
standardizing on a `Python Driver API <api/ironic.drivers.base.html>`_ that
meets the common needs of all hardware vendors, and evolving this API without
breaking backwards compatibility. However, it is sometimes necessary for driver
authors to implement functionality - and expose it through the REST API - that
can not be done through any existing API.

To facilitate that, we also provide the means for API calls to be "passed
through" ironic and directly to the driver. Some guidelines on how to implement
this are provided below. Driver authors are strongly encouraged to talk with
the developer community about any implementation using this functionality.

.. toctree::
  :maxdepth: 1

  Driver Overview <dev/drivers>
  Driver Base Class Definition <api/ironic.drivers.base.html>
  Writing "vendor_passthru" methods <dev/vendor-passthru>

Testing Network Integration
---------------------------

In order to test the integration between the Bare Metal and Networking
services, support has been added to `devstack <http://launchpad.net/devstack>`_
to mimic an external physical switch.  Here we include a recommended
configuration for devstack to bring up this environment.

.. toctree::
  :maxdepth: 1

  Configuring Devstack for multitenant network testing <dev/ironic-multitenant-networking>


Administrator's Guide
=====================

Installation & Operations
-------------------------

If you are a system administrator running Ironic, this section contains
information that should help you understand how to deploy, operate, and upgrade
the services.

.. toctree::
  :maxdepth: 1

  Installation Guide <http://docs.openstack.org/project-install-guide/baremetal/newton/>
  Upgrade Guide <deploy/upgrade-guide>
  Release Notes <http://docs.openstack.org/releasenotes/ironic/>
  Troubleshooting FAQ <deploy/troubleshooting>

Configuration
-------------

There are many aspects of the Bare Metal service which are environment
specific. The following pages will be helpful in configuring specific aspects
of ironic that may or may not be suitable to every situation.

.. toctree::
  :maxdepth: 1

  Guide to Node Cleaning <deploy/cleaning>
  Configuring Node Inspection <deploy/inspection>
  Configuring RAID during deployment <deploy/raid>
  Security considerations for your Bare Metal installation <deploy/security>
  Adopting Nodes in an ACTIVE state <deploy/adoption>
  Auditing API Traffic <deploy/api-audit-support>
  Configuring for Multi-tenant Networking <deploy/multitenancy>
  Configuring node web or serial console <deploy/console>
  Emitting software metrics <deploy/metrics>

A reference guide listing all available configuration options is published for
every major release. Additionally, a `sample configuration file`_ is included
within the project and kept continually up to date.

.. toctree::
  :maxdepth: 1

  Configuration Reference (Newton) <http://docs.openstack.org/newton/config-reference/bare-metal.html>

.. _sample configuration file: https://git.openstack.org/cgit/openstack/ironic/tree/etc/ironic/ironic.conf.sample?h=stable%2Fnewton

Dashboard Integration
---------------------

A plugin for the OpenStack Dashboard (horizon) service is under development.
Documentation for that can be found within the ironic-ui project.

.. toctree::
  :maxdepth: 1

  Dashboard (horizon) plugin <http://docs.openstack.org/developer/ironic-ui/>


Driver References
=================

Every driver author is expected to document the use and configuration of their
driver. These pages are linked below.

.. toctree::
  :maxdepth: 2

  Driver Documentation pages <deploy/drivers>
  Further Considerations for the Agent Drivers <drivers/ipa>

Command References
==================

Here are references for commands not elsewhere documented.

.. toctree::
  :maxdepth: 1

  cmds/ironic-dbsync

Indices and tables
==================

* :ref:`genindex`
* :ref:`modindex`
* :ref:`search`
