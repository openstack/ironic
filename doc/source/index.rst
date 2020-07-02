==================================
Welcome to Ironic's documentation!
==================================

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

This documentation is continually updated and may not represent the state of
the project at any specific prior release. To access documentation for a
previous release of ironic, append the OpenStack release name to the URL; for
example, the ``ocata`` release is available at
https://docs.openstack.org/ironic/ocata/.

Found a bug in one of our projects? Please see :doc:`/contributor/bugs`.

Installation Guide
==================

.. toctree::
  :maxdepth: 2

  install/index

Upgrade Guide
=============

.. toctree::
  :maxdepth: 2

  admin/upgrade-guide
  admin/upgrade-to-hardware-types

User Guide
==========

.. toctree::
  :maxdepth: 2

  user/index

Administrator Guide
===================

.. toctree::
  :maxdepth: 2

  admin/index

Configuration Guide
===================

.. toctree::
  :maxdepth: 2

  configuration/index

Bare Metal API References
=========================

Ironic's REST API has changed since its first release, and continues to evolve
to meet the changing needs of the community.  Here we provide a conceptual
guide as well as more detailed reference documentation.

.. toctree::
  :maxdepth: 1

  API Concept Guide <contributor/webapi>
  API Reference (latest) <https://docs.openstack.org/api-ref/baremetal/>
  API Version History <contributor/webapi-version-history>

Command References
==================

Here are references for commands not elsewhere documented.

.. toctree::
  :maxdepth: 2

  cli/index

Contributor Guide
=================

.. toctree::
   :maxdepth: 2

   contributor/index

Release Notes
=============

`Release Notes <https://docs.openstack.org/releasenotes/ironic/>`_

.. only:: html

   Indices and tables
   ==================

   * :ref:`genindex`
   * :ref:`search`
