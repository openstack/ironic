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

For an in-depth look at the project's scope and structure, see the
:doc:`dev/architecture` page.


Status: Alpha Quality
=====================

Ironic is targeting inclusion in the OpenStack Icehouse release. The current
codebase should be considered "alpha" quality. All major functional components
exist but there are many known bugs which will prevent general use at this
time.  Additionally, usage documentation still needs to be written.

If you are looking for the preceding baremetal service, which was included in
OpenStack Grizzly and Havana releases, please see Nova's `Baremetal driver`_.

.. TODO
.. - installation
.. - configuration
..   - DB and AMQP
..   - API and Conductor services
..   - integration with other OS services
..   - any driver-specific configuration
.. - hardware enrollment
..   - manual vs automatic
..   - hw plugins


Developer Documentation
=======================

Overview
--------

.. toctree::
  :maxdepth: 1

  dev/architecture
  dev/contributing
  dev/dev-quickstart

Client API Reference
--------------------

.. toctree::
  :maxdepth: 1

  webapi/v1

Python API Quick Reference
--------------------------

.. toctree::
  :maxdepth: 1

  dev/api
  dev/common
  dev/db
  dev/drivers
  dev/conductor

Indices and tables
==================

* :ref:`genindex`
* :ref:`modindex`
* :ref:`search`


.. _Baremetal Driver: https://wiki.openstack.org/wiki/Baremetal
