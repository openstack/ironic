.. _drivers:

=================
Pluggable Drivers
=================

Ironic supports a pluggable driver model. This allows contributors to easily
add new drivers, and operators to use third-party drivers or write their own.

Drivers are loaded by the ironic-conductor service during initialization, by
enumerating the python entrypoint "ironic.drivers" and attempting to load
all drivers specified in the "enabled_drivers" configuration option. A
complete list of drivers available on the system may be found by
enumerating this entrypoint by running the following python script::

  #!/usr/bin/env python

  import pkg_resources as pkg
  print [p.name for p in pkg.iter_entry_points("ironic.drivers") if not p.name.startswith("fake")]

A list of drivers enabled in a running Ironic service may be found by issuing
the following command against that API end point::

  ironic driver-list


Supported Drivers
-----------------

For a list of supported drivers (those that are continuously tested on every
upstream commit) please consult the wiki page::

  https://wiki.openstack.org/wiki/Ironic/Drivers

.. toctree::
    ../api/ironic.drivers.base
    ../api/ironic.drivers.pxe
