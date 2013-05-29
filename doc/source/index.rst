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
VM, and so on), then Ironic may be thought of as a *hypervisor API* glueing
together multiple drivers, each of which implement some portion of that
functionality with respect to physical hardware.

For an in-depth look at the project's scope and structure, see the
:doc:`architecture` page.


Status: Hard Hat Required!
==========================

Ironic is under rapid initial development, forked from Nova's `Baremetal
driver`_.  If you're looking for an OpenStack service to provision bare metal
today, that is where you want to look.

.. TODO
.. - installation
.. - configuration
..   - integration with other OS services
..   - single or multiple managers
..   - different drivers
.. - hardware enrollment
..   - manual vs automatic
..   - hw plugins


Developer Docs
==============

For those wishing to develop Ironic itself, or add drivers to extend Ironic's
functionality, the following documentation is provided.

.. toctree::
  :maxdepth: 1

  architecture
  contributing
  dev-quickstart

Client API Reference
--------------------

.. toctree::
  :maxdepth: 1

  api-spec-v1

Python API Quick Reference
--------------------------

.. toctree::
  :maxdepth: 2

  api/api
  api/cmd
  api/common
  api/db
  api/drivers
  api/manager

Indices and tables
==================

* :ref:`genindex`
* :ref:`modindex`
* :ref:`search`


.. _Baremetal Driver: https://wiki.openstack.org/wiki/Baremetal
