Common Considerations
=====================

This section covers considerations that are equally important to all described
architectures.

.. contents::
   :local:

.. _refarch-common-components:

Components
----------

As explained in :doc:`../get_started`, the Bare Metal service has three
components.

* The Bare Metal API service (``ironic-api``) should be deployed in a similar
  way as the control plane API services. The exact location will depend on the
  architecture used.

* The Bare Metal conductor service (``ironic-conductor``) is where most of the
  provisioning logic lives. The following considerations are the most
  important when deciding on the way to deploy it:

  * The conductor manages a certain proportion of nodes, distributed to it
    via a hash ring. This includes constantly polling these nodes for their
    current power state and hardware sensor data (if enabled and supported
    by hardware, see :ref:`ipmi-sensor-data` for an example).

  * The conductor needs access to the `management controller`_ of each node
    it manages.

  * The conductor co-exists with TFTP (for PXE) and/or HTTP (for iPXE) services
    that provide the kernel and ramdisk to boot the nodes. The conductor
    manages them by writing files to their root directories.

  * If serial console is used, the conductor launches console processes
    locally. If the ``nova-serialproxy`` service (part of the Compute service)
    is used, it has to be able to reach the conductors. Otherwise, they have to
    be directly accessible by the users.

  * There must be mutual connectivity between the conductor and the nodes
    being deployed or cleaned. See Networking_ for details.

* The provisioning ramdisk which runs the ``ironic-python-agent`` service
  on start up.

  .. warning::
    The ``ironic-python-agent`` service is not intended to be used or executed
    anywhere other than a provisioning/cleaning/rescue ramdisk.

Hardware and drivers
--------------------

The Bare Metal service strives to provide the best support possible for a
variety of hardware. However, not all hardware is supported equally well.
It depends on both the capabilities of hardware itself and the available
drivers. This section covers various considerations related to the hardware
interfaces. See :doc:`/install/enabling-drivers` for a detailed introduction
into hardware types and interfaces before proceeding.

Power and management interfaces
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

The minimum set of capabilities that the hardware has to provide and the
driver has to support is as follows:

#. getting and setting the power state of the machine
#. getting and setting the current boot device
#. booting an image provided by the Bare Metal service (in the simplest case,
   support booting using PXE_ and/or iPXE_)

.. note::
    Strictly speaking, it is possible to make the Bare Metal service provision
    nodes without some of these capabilities via some manual steps. It is not
    the recommended way of deployment, and thus it is not covered in this
    guide.

Once you make sure that the hardware supports these capabilities, you need to
find a suitable driver. Most of enterprise-grade hardware has support for
IPMI_ and thus can utilize :doc:`/admin/drivers/ipmitool`. Some newer hardware
also supports :doc:`/admin/drivers/redfish`. Several vendors
provide more specific drivers that usually provide additional capabilities.
Check :doc:`/admin/drivers` to find the most suitable one.

.. _refarch-common-boot:

Boot interface
~~~~~~~~~~~~~~

The boot interface of a node manages booting of both the deploy ramdisk and
the user instances on the bare metal node. The deploy interface orchestrates
the deployment and defines how the image gets transferred to the target disk.

The main alternatives are to use PXE/iPXE or virtual media - see
:doc:`/admin/interfaces/boot` for a detailed explanation. If a virtual media
implementation is available for the hardware, it is recommended using it
for better scalability and security. Otherwise, it is recommended to use iPXE,
when it is supported by target hardware.

Hardware specifications
~~~~~~~~~~~~~~~~~~~~~~~

The Bare Metal services does not impose too many restrictions on the
characteristics of hardware itself. However, keep in mind that

* By default, the Bare Metal service will pick the smallest hard drive that
  is larger than 4 GiB for deployment. Another hard drive can be used, but it
  requires setting :ref:`root device hints <root-device-hints>`.

  .. note::
    This device does not have to match the boot device set in BIOS (or similar
    firmware).

* The machines should have enough RAM to fit the deployment/cleaning ramdisk
  to run. The minimum varies greatly depending on the way the ramdisk was
  built. For example, *tinyipa*, the TinyCoreLinux-based ramdisk used in the
  CI, only needs 400 MiB of RAM, while ramdisks built by *diskimage-builder*
  may require 3 GiB or more.

Image types
-----------

The Bare Metal service can deploy two types of images:

* *Whole-disk* images that contain a complete partitioning table with all
  necessary partitions and a bootloader. Such images are the most universal,
  but may be harder to build.

* *Partition images* that contain only the root partition. The Bare Metal
  service will create the necessary partitions and install a boot loader,
  if needed.

  .. warning::
    Partition images are only supported with GNU/Linux operating systems.

  .. warning::
    If you plan on using local boot, your partition images must contain GRUB2
    bootloader tools to enable ironic to set up the bootloader during deploy.

Local vs network boot
---------------------

The Bare Metal service supports booting user instances either using a local
bootloader or using the driver's boot interface (e.g. via PXE_ or iPXE_
protocol in case of the ``pxe`` interface).

Network boot cannot be used with certain architectures (for example, when no
tenant networks have access to the control plane).

Additional considerations are related to the ``pxe`` boot interface, and other
boot interfaces based on it:

* Local boot makes node's boot process independent of the Bare Metal conductor
  managing it. Thus, nodes are able to reboot correctly, even if the Bare Metal
  TFTP or HTTP service is down.

* Network boot (and iPXE) must be used when booting nodes from remote volumes,
  if the driver does not support attaching volumes out-of-band.

The default boot option for the cloud can be changed via the Bare Metal service
configuration file, for example:

.. code-block:: ini

    [deploy]
    default_boot_option = local

This default can be overridden by setting the ``boot_option`` capability on a
node. See :ref:`local-boot-partition-images` for details.

.. note::
    Currently, local boot is used by default. It's safer to set
    the ``default_boot_option`` explicitly.

.. _refarch-common-networking:

Networking
----------

There are several recommended network topologies to be used with the Bare
Metal service. They are explained in depth in specific architecture
documentation. However, several considerations are common for all of them:

* There has to be a *provisioning* network, which is used by nodes during
  the deployment process. If allowed by the architecture, this network should
  not be accessible by end users, and should not have access to the internet.

* There has to be a *cleaning* network, which is used by nodes during
  the cleaning process.

* There should be a *rescuing* network, which is used by nodes during
  the rescue process. It can be skipped if the rescue process is not supported.

.. note::
    In the majority of cases, the same network should be used for cleaning,
    provisioning and rescue for simplicity.

Unless noted otherwise, everything in these sections apply to all three
networks.

* The baremetal nodes must have access to the Bare Metal API while connected
  to the provisioning/cleaning/rescuing network.

  .. note::
      Only two endpoints need to be exposed there::

        GET /v1/lookup
        POST /v1/heartbeat/[a-z0-9\-]+

      You may want to limit access from this network to only these endpoints,
      and make these endpoint not accessible from other networks.

* If the ``pxe`` boot interface (or any boot interface based on it) is used,
  then the baremetal nodes should have untagged (access mode) connectivity
  to the provisioning/cleaning/rescuing networks. It allows PXE firmware, which
  does not support VLANs, to communicate with the services required
  for provisioning.

  .. note::
      It depends on the *network interface* whether the Bare Metal service will
      handle it automatically. Check the networking documentation for the
      specific architecture.

  Sometimes it may be necessary to disable the spanning tree protocol delay on
  the switch - see :ref:`troubleshooting-stp`.

* The Baremetal nodes need to have access to any services required for
  provisioning/cleaning/rescue, while connected to the
  provisioning/cleaning/rescuing network. This may include:

  * a TFTP server for PXE boot and also an HTTP server when iPXE is enabled
  * either an HTTP server or the Object Storage service in case of the
    ``direct`` deploy interface and some virtual media boot interfaces

* The Baremetal Conductors need to have access to the booted baremetal nodes
  during provisioning/cleaning/rescue. A conductor communicates with
  an internal API, provided by **ironic-python-agent**, to conduct actions
  on nodes.

.. _refarch-common-ha:

HA and Scalability
------------------

ironic-api
~~~~~~~~~~

The Bare Metal API service is stateless, and thus can be easily scaled
horizontally. It is recommended to deploy it as a WSGI application behind e.g.
Apache or another WSGI container.

.. note::
    This service accesses the ironic database for reading entities (e.g. in
    response to ``GET /v1/nodes`` request) and in rare cases for writing.

ironic-conductor
~~~~~~~~~~~~~~~~

High availability
^^^^^^^^^^^^^^^^^

The Bare Metal conductor service utilizes the active/active HA model. Every
conductor manages a certain subset of nodes. The nodes are organized in a hash
ring that tries to keep the load spread more or less uniformly across the
conductors. When a conductor is considered offline, its nodes are taken over by
other conductors. As a result of this, you need at least 2 conductor hosts
for an HA deployment.

Performance
^^^^^^^^^^^

Conductors can be resource intensive, so it is recommended (but not required)
to keep all conductors separate from other services in the cloud. The minimum
required number of conductors in a deployment depends on several factors:

* the performance of the hardware where the conductors will be running,
* the speed and reliability of the `management controller`_ of the
  bare metal nodes (for example, handling slower controllers may require having
  less nodes per conductor),
* the frequency, at which the management controllers are polled by the Bare
  Metal service (see the ``sync_power_state_interval`` option),
* the bare metal driver used for nodes (see `Hardware and drivers`_ above),
* the network performance,
* the maximum number of bare metal nodes that are provisioned simultaneously
  (see the ``max_concurrent_builds`` option for the Compute service).

We recommend a target of **100** bare metal nodes per conductor for maximum
reliability and performance. There is some tolerance for a larger number per
conductor. However, it was reported [1]_ [2]_ that reliability degrades when
handling approximately 300 bare metal nodes per conductor.

Disk space
^^^^^^^^^^

Each conductor needs enough free disk space to cache images it uses.
Depending on the combination of the deploy interface and the boot option,
the space requirements are different:

* The deployment kernel and ramdisk are always cached during the deployment.

* When ``[agent]image_download_source`` is set to ``http`` and Glance is used,
  the conductor will download instances images locally to serve them from its
  HTTP server. Use ``swift`` to publish images using temporary URLs and convert
  them on the node's side.

  When ``[agent]image_download_source`` is set to ``local``, it will happen
  even for HTTP(s) URLs. For standalone case use ``http`` to avoid unnecessary
  caching of images.

  In both cases a cached image is converted to raw if ``force_raw_images``
  is ``True`` (the default).

  .. note::
    ``image_download_source`` can also be provided in the node's
    ``driver_info`` or ``instance_info``. See :ref:`image_download_source`.

* When network boot is used, the instance image kernel and ramdisk are cached
  locally while the instance is active.

.. note::
    All images may be stored for some time after they are no longer needed.
    This is done to speed up simultaneous deployments of many similar images.
    The caching can be configured via the ``image_cache_size`` and
    ``image_cache_ttl`` configuration options in the ``pxe`` group.

.. [1] http://lists.openstack.org/pipermail/openstack-dev/2017-June/118033.html
.. [2] http://lists.openstack.org/pipermail/openstack-dev/2017-June/118327.html

Other services
~~~~~~~~~~~~~~

When integrating with other OpenStack services, more considerations may need
to be applied. This is covered in other parts of this guide.


.. _PXE: https://en.wikipedia.org/wiki/Preboot_Execution_Environment
.. _iPXE: https://en.wikipedia.org/wiki/IPXE
.. _IPMI: https://en.wikipedia.org/wiki/Intelligent_Platform_Management_Interface
.. _management controller: https://en.wikipedia.org/wiki/Out-of-band_management
