Small cloud with trusted tenants
================================

Story
-----

As an operator I would like to build a small cloud with both virtual and bare
metal instances or add bare metal provisioning to my existing small or medium
scale single-site OpenStack cloud. The expected number of bare metal machines
is less than 100, and the rate of provisioning and unprovisioning is expected
to be low. All users of my cloud are trusted by me to not conduct malicious
actions towards each other or the cloud infrastructure itself.

As a user I would like to occasionally provision bare metal instances through
the Compute API by selecting an appropriate Compute flavor. I would like
to be able to boot them from images provided by the Image service or from
volumes provided by the Volume service.

Components
----------

This architecture assumes `an OpenStack installation`_ with the following
components participating in the bare metal provisioning:

* The `Compute service`_ manages bare metal instances.

* The `Networking service`_ provides DHCP for bare metal instances.

* The `Image service`_ provides images for bare metal instances.

The following services can be optionally used by the Bare Metal service:

* The `Volume service`_ provides volumes to boot bare metal instances from.

* The `Bare Metal Introspection service`_ simplifies enrolling new bare metal
  machines by conducting in-band introspection.

Node roles
----------

An OpenStack installation in this guide has at least these three types of
nodes:

* A *controller* node hosts the control plane services.

* A *compute* node runs the virtual machines and hosts a subset of Compute
  and Networking components.

* A *block storage* node provides persistent storage space for both virtual
  and bare metal nodes.

The *compute* and *block storage* nodes are configured as described in the
installation guides of the `Compute service`_ and the `Volume service`_
respectively. The *controller* nodes host the Bare Metal service components.

Networking
----------

The networking architecture will highly depend on the exact operating
requirements. This guide expects the following existing networks:
*control plane*, *storage* and *public*. Additionally, two more networks
will be needed specifically for bare metal provisioning: *bare metal* and
*management*.

.. TODO(dtantsur): describe the storage network?

.. TODO(dtantsur): a nice picture to illustrate the layout

Control plane network
~~~~~~~~~~~~~~~~~~~~~

The *control plane network* is the network where OpenStack control plane
services provide their public API.

The Bare Metal API will be served to the operators and to the Compute service
through this network.

Public network
~~~~~~~~~~~~~~

The *public network* is used in a typical OpenStack deployment to create
floating IPs for outside access to instances. Its role is the same for a bare
metal deployment.

.. note::
    Since, as explained below, bare metal nodes will be put on a flat provider
    network, it is also possible to organize direct access to them, without
    using floating IPs and bypassing the Networking service completely.

Bare metal network
~~~~~~~~~~~~~~~~~~

The *Bare metal network* is a dedicated network for bare metal nodes managed by
the Bare Metal service.

This architecture uses :ref:`flat bare metal networking <network-interfaces>`,
in which both tenant traffic and technical traffic related to the Bare Metal
service operation flow through this one network. Specifically, this network
will serve as the *provisioning*, *cleaning* and *rescuing* network. It will
also be used for introspection via the Bare Metal Introspection service.
See :ref:`common networking considerations <refarch-common-networking>` for
an in-depth explanation of the networks used by the Bare Metal service.

DHCP and boot parameters will be provided on this network by the Networking
service's DHCP agents.

For booting from volumes this network has to have a route to
the *storage network*.

Management network
~~~~~~~~~~~~~~~~~~

*Management network* is an independent network on which BMCs of the bare
metal nodes are located.

The ``ironic-conductor`` process needs access to this network. The tenants
of the bare metal nodes must not have access to it.

.. note::
    The :ref:`direct deploy interface <direct-deploy>` and certain
    :doc:`/admin/drivers` require the *management network* to have access
    to the Object storage service backend.

Controllers
-----------

A *controller* hosts the OpenStack control plane services as described in the
`control plane design guide`_. While this architecture allows using
*controllers* in a non-HA configuration, it is recommended to have at least
three of them for HA. See :ref:`refarch-common-ha` for more details.

Bare Metal services
~~~~~~~~~~~~~~~~~~~

The following components of the Bare Metal service are installed on a
*controller* (see :ref:`components of the Bare Metal service
<refarch-common-components>`):

* The Bare Metal API service either as a WSGI application or the ``ironic-api``
  process. Typically, a load balancer, such as HAProxy, spreads the load
  between the API instances on the *controllers*.

  The API has to be served on the *control plane network*. Additionally,
  it has to be exposed to the *bare metal network* for the ramdisk callback
  API.

* The ``ironic-conductor`` process. These processes work in active/active HA
  mode as explained in :ref:`refarch-common-ha`, thus they can be installed on
  all *controllers*. Each will handle a subset of bare metal nodes.

  The ``ironic-conductor`` processes have to have access to the following
  networks:

  * *control plane* for interacting with other services
  * *management* for contacting node's BMCs
  * *bare metal* for contacting deployment, cleaning or rescue ramdisks

* TFTP and HTTP service for booting the nodes. Each ``ironic-conductor``
  process has to have a matching TFTP and HTTP service. They should be exposed
  only to the *bare metal network* and must not be behind a load balancer.

* The ``nova-compute`` process (from the Compute service). These processes work
  in active/active HA mode when dealing with bare metal nodes, thus they can be
  installed on all *controllers*. Each will handle a subset of bare metal
  nodes.

  .. note::
    There is no 1-1 mapping between ``ironic-conductor`` and ``nova-compute``
    processes, as they communicate only through the Bare Metal API service.

* The networking-baremetal_ ML2 plugin should be loaded into the Networking
  service to assist with binding bare metal ports.

  The ironic-neutron-agent_ service should be started as well.

* If the Bare Metal introspection is used, its ``ironic-inspector`` process
  has to be installed on all *controllers*. Each such process works as both
  Bare Metal Introspection API and conductor service. A load balancer should
  be used to spread the API load between *controllers*.

  The API has to be served on the *control plane network*. Additionally,
  it has to be exposed to the *bare metal network* for the ramdisk callback
  API.

.. TODO(dtantsur): a nice picture to illustrate the above

Shared services
~~~~~~~~~~~~~~~

A *controller* also hosts two services required for the normal operation
of OpenStack:

* Database service (MySQL/MariaDB is typically used, but other
  enterprise-grade database solutions can be used as well).

  All Bare Metal service components need access to the database service.

* Message queue service (RabbitMQ is typically used, but other
  enterprise-grade message queue brokers can be used as well).

  Both Bare Metal API (WSGI application or ``ironic-api`` process) and
  the ``ironic-conductor`` processes need access to the message queue service.
  The Bare Metal Introspection service does not need it.

.. note::
    These services are required for all OpenStack services. If you're adding
    the Bare Metal service to your cloud, you may reuse the existing
    database and messaging queue services.

Bare metal nodes
----------------

Each bare metal node must be capable of booting from network, virtual media
or other boot technology supported by the Bare Metal service as explained
in :ref:`refarch-common-boot`. Each node must have one NIC on the *bare metal
network*, and this NIC (and **only** it) must be configured to be able to boot
from network. This is usually done in the *BIOS setup* or a similar firmware
configuration utility. There is no need to alter the boot order, as it is
managed by the Bare Metal service. Other NICs, if present, will not be managed
by OpenStack.

The NIC on the *bare metal network* should have untagged connectivity to it,
since PXE firmware usually does not support VLANs - see
:ref:`refarch-common-networking` for details.

Storage
-------

If your hardware **and** its bare metal :doc:`driver </admin/drivers>` support
booting from remote volumes, please check the driver documentation for
information on how to enable it. It may include routing *management* and/or
*bare metal* networks to the *storage network*.

In case of the standard :ref:`pxe-boot`, booting from remote volumes is done
via iPXE. In that case, the Volume storage backend must support iSCSI_
protocol, and the *bare metal network* has to have a route to the *storage
network*. See :doc:`/admin/boot-from-volume` for more details.

.. _an OpenStack installation: https://docs.openstack.org/arch-design/use-cases/use-case-general-compute.html
.. _Compute service: https://docs.openstack.org/nova/train/
.. _Networking service: https://docs.openstack.org/neutron/train/
.. _Image service: https://docs.openstack.org/glance/train/
.. _Volume service: https://docs.openstack.org/cinder/train/
.. _Bare Metal Introspection service: https://docs.openstack.org/ironic-inspector/train/
.. _control plane design guide: https://docs.openstack.org/arch-design/design-control-plane.html
.. _networking-baremetal: https://docs.openstack.org/networking-baremetal/train/
.. _ironic-neutron-agent: https://docs.openstack.org/networking-baremetal/train/install/index.html#configure-ironic-neutron-agent
.. _iSCSI: https://en.wikipedia.org/wiki/ISCSI
