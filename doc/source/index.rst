============================================
Welcome to Ironic's developer documentation!
============================================

Introduction
============

Ironic is an OpenStack project which provisions bare metal (as opposed to
virtual) machines by leveraging common technologies such as PXE boot and IPMI
to cover a wide range of hardware, while supporting pluggable drivers to allow
vendor-specific functionality to be added.

If one thinks of traditional hypervisor functionality (eg, creating a VM,
enumerating virtual devices, managing the power state, loading an OS onto the
VM, and so on), then Ironic may be thought of as a *hypervisor API* gluing
together multiple drivers, each of which implement some portion of that
functionality with respect to physical hardware.

The documentation provided here is continually kept up-to-date based
on the latest code, and may not represent the state of the project at any
specific prior release.

For information on any current or prior version of Ironic, see `the release
notes`_.

.. _the release notes: http://docs.openstack.org/releasenotes/ironic/

Administrator's Guide
=====================

.. toctree::
  :maxdepth: 1

  deploy/user-guide
  Installation Guide <deploy/install-guide>
  Upgrade Guide <deploy/upgrade-guide>
  Configuration Reference (Mitaka) <http://docs.openstack.org/mitaka/config-reference/bare-metal.html>
  drivers/ipa
  deploy/drivers
  deploy/cleaning
  deploy/raid
  deploy/inspection
  deploy/security
  deploy/adoption
  deploy/api-audit-support
  deploy/troubleshooting
  Release Notes <http://docs.openstack.org/releasenotes/ironic/>
  Dashboard (horizon) plugin <http://docs.openstack.org/developer/ironic-ui/>

Commands and API References
===========================

.. toctree::
  :maxdepth: 1

  cmds/ironic-dbsync
  webapi/v1
  dev/drivers

Developer's Guide
=================

.. toctree::
  :maxdepth: 1

  dev/architecture
  dev/states
  dev/contributing
  dev/code-contribution-guide
  dev/dev-quickstart
  dev/vendor-passthru
  dev/ironic-multitenant-networking

  dev/faq

Indices and tables
==================

* :ref:`genindex`
* :ref:`modindex`
* :ref:`search`
