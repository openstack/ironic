============================================
Welcome to Ironic's developer documentation!
============================================

Ironic is an :term:`Incubated` OpenStack project which aims to provision bare
metal (as opposed to virtual) machines by leveraging common technologies such
as PXE boot and IPMI to cover a wide range of hardware, while supporting
pluggable drivers to allow vendor-specific functionality to be added.

If one thinks of traditional hypervisor functionality (eg, creating a VM,
enumerating virtual devices, managing the power state, loading an OS onto the
VM, and so on), then Ironic may be thought of as a *hypervisor API* glueing
together multiple drivers, each of which implement some portion of that
functionality with respect to physical hardware.


Table of contents
=================

.. toctree::
  :maxdepth: 1

  architecture
  contributing/index
  api/index

.. - installation
.. - configuration
..   - integration with other OS services
..   - single or multiple managers
..   - different drivers
.. - hardware enrollment
..   - manual vs automatic
..   - hw plugins

Indices and tables
==================

* :ref:`genindex`
* :ref:`modindex`
* :ref:`search`

