============================================
Welcome to Ironic's developer documentation!
============================================

Introduction
============

Ironic is an Incubated OpenStack project which aims to provision bare
metal (as opposed to virtual) machines by leveraging common technologies such
as PXE boot and IPMI to cover a wide range of hardware, while supporting
pluggable drivers to allow vendor-specific functionality to be added.

If one thinks of traditional hypervisor functionality (eg, creating a VM,
enumerating virtual devices, managing the power state, loading an OS onto the
VM, and so on), then Ironic may be thought of as a *hypervisor API* gluing
together multiple drivers, each of which implement some portion of that
functionality with respect to physical hardware.

Ironic should be considered Beta quality as of the Icehouse release, and will
make the best effort to maintain backwards compatibility from this point
forward. Release notes are available here:
https://wiki.openstack.org/wiki/Ironic/ReleaseNotes/Icehouse

The developer documentation provided here is continually kept up-to-date based
on the latest code, and may not represent the state of our APIs at any given
release.

Developer Guide
===============

Introduction
------------

.. toctree::
  :maxdepth: 1

  dev/architecture
  dev/contributing

.. toctree::
  dev/dev-quickstart

API References
--------------

.. toctree::
  :maxdepth: 1

  webapi/v1
  dev/common
  dev/db
  dev/drivers

Admin Guide
===========

Overview
--------

.. toctree::
  :maxdepth: 1

  deploy/user-guide
  deploy/install-guide
  deploy/drivers

Commands
--------

.. toctree::
  :maxdepth: 1

  cmds/ironic-dbsync

Indices and tables
==================

* :ref:`genindex`
* :ref:`modindex`
* :ref:`search`
