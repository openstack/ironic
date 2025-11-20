======
Ironic
======

.. image:: https://governance.openstack.org/tc/badges/ironic.svg

Overview
--------

Ironic consists of an API and plug-ins for managing and provisioning
physical machines in a security-aware and fault-tolerant manner. It can be
used with nova as a hypervisor driver, or standalone service.

By default, it will use PXE and IPMI/Redfish to interact with bare metal
machines. Some drivers, like the Redfish drivers, also support advanced
features like leveraging HTTPBoot or Virtual Media based boot operations
depending on the configuration by the user. Ironic also supports
vendor-specific plug-ins which may implement additional functionality,
however many vendors have chosen to focus on their Redfish implementations
instead of customized drivers.

Numerous ways exist to leverage Ironic to deploy a bare metal node, above
and beyond asking Nova for a "bare metal" instance, or for asking Ironic
to manually deploy a specific machine. Bifrost and Metal3 are related
projects which seek to simplify the use and interaction of Ironic.

Ironic is distributed under the terms of the Apache License, Version 2.0. The
full terms and conditions of this license are detailed in the LICENSE file.

Project resources
~~~~~~~~~~~~~~~~~

* Documentation: https://docs.openstack.org/ironic/latest
* Source: https://opendev.org/openstack/ironic
* Bugs: https://bugs.launchpad.net/ironic/+bugs
* Wiki: https://wiki.openstack.org/wiki/Ironic
* APIs: https://docs.openstack.org/api-ref/baremetal/index.html
* Release Notes: https://docs.openstack.org/releasenotes/ironic/
* Design Specifications: https://specs.openstack.org/openstack/ironic-specs/

Project status, bugs, and requests for feature enhancements (RFEs) are tracked
in Launchpad:
https://launchpad.net/ironic

For information on how to contribute to ironic, see
https://docs.openstack.org/ironic/latest/contributor
