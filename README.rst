Ironic
======

Ironic is an integrated OpenStack project which aims to provision bare
metal machines instead of virtual machines, forked from the Nova Baremetal
driver. It is best thought of as a bare metal hypervisor **API** and a set
of plugins which interact with the bare metal hypervisors. By default, it
will use PXE and IPMI together to provision and turn on/off machines,
but Ironic also supports vendor-specific plugins which may implement
additional functionality.

-----------------
Project Resources
-----------------

* Free software: Apache license
* Documentation: http://docs.openstack.org/developer/ironic
* Source: http://git.openstack.org/cgit/openstack/ironic
* Bugs: http://bugs.launchpad.net/ironic
* Wiki: https://wiki.openstack.org/wiki/Ironic

Project status, bugs and RFEs (requests for feature enhancements)
are tracked on Launchpad:

  http://launchpad.net/ironic

Anyone wishing to contribute to an OpenStack project should
find a good reference here:

  http://docs.openstack.org/infra/manual/developers.html
