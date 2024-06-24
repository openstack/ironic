Developer's Guide
=================

Getting Started
---------------

If you are new to ironic, this section contains information that should help
you get started as a developer working on the project or contributing to the
project.

This guide assumes you have read the
`OpenDev getting started documentation <https://docs.opendev.org/opendev/infra-manual/latest/gettingstarted.html>`_.
It will also be helpful to be familiar with
`OpenStack contributors documentation <https://docs.openstack.org/contributors/code-and-documentation/>`_,
which contains basic information about how to use many of the community tools
and OpenStack practices.

Basic information about setting up development environments with devstack
or bifrost, or getting unit tests running can be found here:

.. toctree::
   :maxdepth: 2

   dev-quickstart
   devstack-guide
   bifrost-dev-guide
   local-dev-guide

.. toctree::
   :hidden:

   states

Bugs
----
Information about how ironic projects handle bugs can be found below.

.. toctree::
  :maxdepth: 2

  Bugs Reporting and Triaging Guide <bugs>
  Bug Deputy Guide <bug-deputy>

Community and Policies
----------------------

.. toctree::
  :maxdepth: 2

  Bare Metal Community <community>
  Developer Contribution Guide <contributing>
  Specifications <https://specs.openstack.org/openstack/ironic-specs/>
  Frequently Asked Questions <faq>
  Contributor Vision <vision>
  OpenStack Vision <vision-reflection>

Architecture and Implementation Details
---------------------------------------

The following pages describe the architecture of the Bare Metal service
and may be helpful to anyone working on or with the service, but are written
primarily for developers.

.. toctree::
  :maxdepth: 2

  Ironic System Architecture <architecture>
  Developing New Notifications <notifications>
  OSProfiler Tracing <osprofiler-support>
  Rolling Upgrades <rolling-upgrades>
  Role Based Access Control Testing <rbac-testing>

Governance and Processes
------------------------

These pages contain information for PTLs, cross-project liaisons, and core
reviewers.

.. toctree::
  :maxdepth: 2

  Releasing Ironic Projects <releasing>
  Ironic Governance Structure <governance>

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
  :maxdepth: 2

  Driver Overview <drivers>
  Writing "vendor_passthru" Methods <vendor-passthru>
  Creating New BIOS Interfaces <bios_develop>
  Third Party Continuous Integration Testing <third-party-ci>
  Writing Deploy or Clean Steps <deploy-steps>

Full Ironic Server Python API Reference
---------------------------------------

.. toctree::
  :maxdepth: 2

  Python Modules Index <api/modules>

Understanding the Ironic's CI
-----------------------------

It's important to understand the role of each job in the CI, how to add new jobs
and how to debug failures that may arise. To facilitate that, we have created
the documentation below.

.. toctree::
  :maxdepth: 2

  Job Roles in the CI <jobs-description>
  How to Add a New Job? <adding-new-job>
  How to Debug Failures in CI Jobs <debug-ci-failures>
