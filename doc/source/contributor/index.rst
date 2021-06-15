Developer's Guide
=================

Getting Started
---------------

If you are new to ironic, this section contains information that should help
you get started as a developer working on the project or contributing to the
project.

.. toctree::
  :maxdepth: 1

  Bare Metal Community <community>
  Developer Contribution Guide <contributing>
  Bugs Reporting and Triaging Guide <bugs>
  Setting Up Your Development Environment <dev-quickstart>
  Priorities <https://specs.openstack.org/openstack/ironic-specs/#priorities>
  Specifications <https://specs.openstack.org/openstack/ironic-specs/>
  Frequently Asked Questions <faq>
  Contributor Vision <vision>
  OpenStack Vision <vision-reflection>

The following pages describe the architecture of the Bare Metal service
and may be helpful to anyone working on or with the service, but are written
primarily for developers.

.. toctree::
  :maxdepth: 1

  Ironic System Architecture <architecture>
  Developing New Notifications <notifications>
  OSProfiler Tracing <osprofiler-support>
  Rolling Upgrades <rolling-upgrades>
  Role Based Access Control Testing <rbac-testing>

These pages contain information for PTLs, cross-project liaisons, and core
reviewers.

.. toctree::
  :maxdepth: 1

  Releasing Ironic Projects <releasing>
  Ironic Governance Structure <governance>

.. toctree::
   :hidden:

   states

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

  Driver Overview <drivers>
  Writing "vendor_passthru" methods <vendor-passthru>
  Creating new BIOS interfaces <bios_develop>
  Third party continuous integration testing <third-party-ci>
  Writing Deploy or Clean Steps <deploy-steps>

Testing Network Integration
---------------------------

In order to test the integration between the Bare Metal and Networking
services, support has been added to `devstack <https://docs.openstack.org/devstack/latest/>`_
to mimic an external physical switch.  Here we include a recommended
configuration for devstack to bring up this environment.

.. toctree::
  :maxdepth: 1

  Configuring Devstack for multitenant network testing <ironic-multitenant-networking>

Testing Boot-from-Volume
------------------------

Starting with the Pike release, it is also possible to use DevStack for testing
booting from Cinder volumes with VMs.

.. toctree::
  :maxdepth: 1

  Configuring Devstack for boot-from-volume testing <ironic-boot-from-volume>

Full Ironic Server Python API Reference
---------------------------------------

.. toctree::
  :maxdepth: 1

  api/modules

Understanding the Ironic's CI
-----------------------------

It's important to understand the role of each job in the CI, how to add new jobs
and how to debug failures that may arise. To facilitate that, we have created
the documentation below.

.. toctree::
  :maxdepth: 1

  Job roles in the CI <jobs-description>
  How to add a new job? <adding-new-job>
  How to debug failures in CI jobs <debug-ci-failures>

Our policy for stable branches
------------------------------

Stable branches that are on `Extended Maintenance`_ and haven't received
backports in a while, can be tagged as ``Unmaintained``, after discussions
within the ironic community. If such a decision is taken, an email will
be sent to the OpenStack mailing list.

What does ``Unmaintained`` mean? The branch still exists, but the ironic
upstream community will not actively backport patches from maintained
branches. Fixes can still be merged, though, if pushed into review by
operators or other downstream developers. It also means that branchless
projects (e.g.: ironic-tempest-plugin), may not have configurations that are
compatible with those branches.

As of 09 March 2020, the list of ``Unmaintained`` branches includes:

* Ocata (Last commit - Jun 28, 2019)
* Pike (Last commit - Oct 2, 2019)

.. _Extended Maintenance: https://docs.openstack.org/project-team-guide/stable-branches.html#maintenance-phases
