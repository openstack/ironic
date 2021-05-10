=============================
Bare Metal Service User Guide
=============================

Ironic is an OpenStack project which provisions bare metal (as opposed to
virtual) machines. It may be used independently or as part of an OpenStack
Cloud, and integrates with the OpenStack Identity (keystone), Compute (nova),
Network (neutron), Image (glance) and Object (swift) services.

When the Bare Metal service is appropriately configured with the Compute and
Network services, it is possible to provision both virtual and physical
machines through the Compute service's API. However, the set of instance
actions is limited, arising from the different characteristics of physical
servers and switch hardware. For example, live migration can not be performed
on a bare metal instance.

The community maintains reference drivers that leverage open-source
technologies (eg. PXE and IPMI) to cover a wide range of hardware. Ironic's
pluggable driver architecture also allows hardware vendors to write and
contribute drivers that may improve performance or add functionality not
provided by the community drivers.

.. toctree::
  :maxdepth: 2

  architecture
  creating-images
  deploy
