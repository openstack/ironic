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

The developer documentation provided here is continually kept up-to-date based
on the latest code, and may not represent the state of the project at any
specific prior release.

Developer Guide
===============

Introduction
------------

.. toctree::
  :maxdepth: 1

  dev/architecture
  dev/states
  dev/contributing

.. toctree::
  dev/dev-quickstart
  dev/vendor-passthru

API References
--------------

.. toctree::
  :maxdepth: 1

  webapi/v1
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
