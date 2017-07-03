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

:doc:`An introduction to ironic's conceptual architecture <user/index>`
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

  API Concept Guide <contributor/webapi>
  API Reference (latest) <http://developer.openstack.org/api-ref/baremetal/>
  API Reference (latest) <api/index>
  API Version History <contributor/webapi-version-history>


Contributor's Guide
===================

.. toctree::
   :maxdepth: 2

   contributor/index

Administrator's Guide
=====================

.. toctree::
  :maxdepth: 1

  admin/index

Driver References
=================

Every driver author is expected to document the use and configuration of their
driver. These pages are linked below.

.. toctree::
  :maxdepth: 1

  Driver Documentation pages <admin/drivers>
  Further Considerations for the Agent Drivers <admin/drivers/ipa>

Command References
==================

Here are references for commands not elsewhere documented.

.. toctree::
  :maxdepth: 2

  cli/index

Indices and tables
==================

* :ref:`genindex`
* :ref:`search`

.. # NOTE(jaegerandi): This is where we hide things that we don't want
   # shown in the top level table of contents.
   # user/index is referenced above but not in a toctree.
.. toctree::
   :hidden:

   admin/install-guide.rst
   user/index
   releasenotes/index
   webapi/v1.rst
   admin/index
