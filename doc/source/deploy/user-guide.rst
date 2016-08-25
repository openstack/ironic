.. _user-guide:

======================
Introduction to Ironic
======================

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

.. TODO: the remainder of this file needs to be cleaned up still

Why Provision Bare Metal
========================

Here are a few use-cases for bare metal (physical server) provisioning in
cloud; there are doubtless many more interesting ones:

- High-performance computing clusters
- Computing tasks that require access to hardware devices which can't be
  virtualized
- Database hosting (some databases run poorly in a hypervisor)
- Single tenant, dedicated hardware for performance, security, dependability
  and other regulatory requirements
- Or, rapidly deploying a cloud infrastructure

Conceptual Architecture
=======================

The following diagram shows the relationships and how all services come into
play during the provisioning of a physical server. (Note that Ceilometer and
Swift can be used with Ironic, but are missing from this diagram.)


.. figure:: ../images/conceptual_architecture.png
   :alt: ConceptualArchitecture

Logical Architecture
====================

The diagram below shows the logical architecture. It shows the basic
components that form the Ironic service, the relation of Ironic service with
other OpenStack services and the logical flow of a boot instance request
resulting in the provisioning of a physical server.

.. figure:: ../images/logical_architecture.png
   :alt: Logical Architecture

The Ironic service is composed of the following components:

#. a RESTful API service, by which operators and other services may interact
   with the managed bare metal servers.

#. a Conductor service, which does the bulk of the work. Functionality is
   exposed via the API service. The Conductor and API services communicate
   via RPC.

#. various Drivers that support heterogeneous hardware

#. a Message Queue

#. a Database for storing information about the resources. Among other things,
   this includes the state of the conductors, nodes (physical servers), and
   drivers.

As in Figure 1.2. Logical Architecture, a user request to boot an instance is
passed to the Nova Compute service via Nova API and Nova Scheduler. The Compute
service hands over this request to the Ironic service, where the request passes
from the Ironic API, to the Conductor, to a Driver to successfully provision a
physical server for the user.

Just as the Nova Compute service talks to various OpenStack services like
Glance, Neutron, Swift etc to provision a virtual machine instance, here the
Ironic service talks to the same OpenStack services for image, network and
other resource needs to provision a bare metal instance.


Key Technologies for Bare Metal Hosting
=======================================

Preboot Execution Environment (PXE)
-----------------------------------
PXE is part of the Wired for Management (WfM) specification developed by Intel
and Microsoft. The PXE enables system's BIOS and network interface card (NIC)
to bootstrap a computer from the network in place of a disk. Bootstrapping is
the process by which a system loads the OS into local memory so that it can be
executed by the processor. This capability of allowing a system to boot over a
network simplifies server deployment and server management for administrators.

Dynamic Host Configuration Protocol (DHCP)
------------------------------------------
DHCP is a standardized networking protocol used on Internet Protocol (IP)
networks for dynamically distributing network configuration parameters, such
as IP addresses for interfaces and services. Using PXE, the BIOS uses DHCP to
obtain an IP address for the network interface and to locate the server that
stores the network bootstrap program (NBP).

Network Bootstrap Program (NBP)
-------------------------------
NBP is equivalent to GRUB (GRand Unified Bootloader) or LILO (LInux LOader) -
loaders which are traditionally used in local booting. Like the boot program
in a hard drive environment, the NBP is responsible for loading the OS kernel
into memory so that the OS can be bootstrapped over a network.

Trivial File Transfer Protocol (TFTP)
-------------------------------------
TFTP is a simple file transfer protocol that is generally used for automated
transfer of configuration or boot files between machines in a local
environment.  In a PXE environment, TFTP is used to download NBP over the
network using information from the DHCP server.

Intelligent Platform Management Interface (IPMI)
------------------------------------------------
IPMI is a standardized computer system interface used by system administrators
for out-of-band management of computer systems and monitoring of their
operation. It is a method to manage systems that may be unresponsive or powered
off by using only a network connection to the hardware rather than to an
operating system.


Ironic Deployment Architecture
==============================

The Ironic RESTful API service is used to enroll hardware that Ironic will
manage. A cloud administrator usually registers the hardware, specifying their
attributes such as MAC addresses and IPMI credentials. There can be multiple
instances of the API service.

The Ironic conductor service does the bulk of the work.
For security reasons, it is advisable to place the conductor service on
an isolated host, since it is the only service that requires access to both
the data plane and IPMI control plane.

There can be multiple instances of the conductor service to support
various class of drivers and also to manage fail over. Instances of the
conductor service should be on separate nodes. Each conductor can itself run
many drivers to operate heterogeneous hardware. This is depicted in the
following figure.

The API exposes a list of supported drivers and the names of conductor hosts
servicing them.

.. figure:: ../images/deployment_architecture_2.png
   :alt: Deployment Architecture 2

Understanding Bare Metal Deployment
===================================

What happens when a boot instance request comes in? The below diagram walks
through the steps involved during the provisioning of a bare metal instance.

These pre-requisites must be met before the deployment process:

- Dependent packages to be configured on the Bare Metal service node(s)
  where ironic-conductor is running like tftp-server, ipmi, syslinux etc for
  bare metal provisioning.
- Nova must be configured to make use of the bare metal service endpoint
  and compute driver should be configured to use ironic driver on the Nova
  compute node(s).
- Flavors to be created for the available hardware. Nova must know the flavor
  to boot from.
- Images to be made available in Glance. Listed below are some image types
  required for successful bare metal deployment:

     +  bm-deploy-kernel
     +  bm-deploy-ramdisk
     +  user-image
     +  user-image-vmlinuz
     +  user-image-initrd
- Hardware to be enrolled via Ironic RESTful API service.

.. figure:: ../images/deployment_steps.png
   :alt: Deployment Steps

Deploy Process
-----------------

#. A boot instance request comes in via the Nova API, through the message
   queue to the Nova scheduler.

#. Nova scheduler applies filter and finds the eligible compute node. Nova
   scheduler uses flavor extra_specs detail such as 'cpu_arch',
   'baremetal:deploy_kernel_id', 'baremetal:deploy_ramdisk_id' etc to match
   the target physical node.

#. A spawn task is placed by the driver which contains all information such
   as which image to boot from etc. It invokes the driver.spawn from the
   virt layer of Nova compute.

#. Information about the bare metal node is retrieved from the bare metal
   database and the node is reserved.

#. Images from Glance are pulled down to the local disk of the Ironic
   conductor servicing the bare metal node.

   #. For pxe_* drivers these include all images: both the deploy ramdisk and
      user instance images.

   #. For agent_* drivers only the deploy ramdisk is stored locally. Temporary
      URLs in OpenStack's Object Storage service are created for user instance
      images.

#. Virtual interfaces are plugged in and Neutron API updates DHCP port to
   support PXE/TFTP options.

#. Nova's ironic driver issues a deploy request via the Ironic API to the
   Ironic conductor servicing the bare metal node.

#. PXE driver prepares tftp bootloader.

#. The IPMI driver issues command to enable network boot of a node and power
   it on.

#. The DHCP boots the deploy ramdisk. Next, depending on the exact driver
   used, either the conductor copies the image over iSCSI to the physical node
   (pxe_* group of drivers) or the deploy ramdisk downloads the image from
   a temporary URL (agent_* group of drivers), which can be generated by
   a variety of object stores, e.g. *swift*, *radosgw*, etc, and uploaded
   to OpenStack's Object Storage service. In the former case, the conductor
   connects to the iSCSI end point, partitions volume, "dd" the image and
   closes the iSCSI connection.

   The deployment is done. The Ironic conductor will switch pxe config to service
   mode and notify ramdisk agent on the successful deployment.

#. The IPMI driver reboots the bare metal node. Note that there are 2 power
   cycles during bare metal deployment; the first time when powered-on, the
   images get deployed as mentioned in step 9. The second time as in this case,
   after the images are deployed, the node is powered up.

#. The bare metal node status is updated and the node instance is made
   available.

Example 1: PXE Boot and iSCSI Deploy Process
--------------------------------------------

This process is used with pxe_* family of drivers.

.. seqdiag::
   :scale: 80
   :alt: pxe_ipmi

   diagram {
      Nova; API; Conductor; Neutron; "TFTP/HTTPd"; Node;
      activation = none;
      span_height = 1;
      edge_length = 250;
      default_note_color = white;
      default_fontsize = 14;

      Nova -> API [label = "Set instance_info", note = "image_source\n,root_gb,etc."];
      Nova -> API [label = "Set provision_state"];
      API -> Conductor [label = "do_node_deploy()"];
      Conductor -> Conductor [label = "Cache images"];
      Conductor -> Conductor [label = "Build TFTP config"];
      Conductor -> Neutron [label = "Update DHCPBOOT"];
      Conductor -> Node [label = "IPMI power-on"];
      Node -> Neutron [label = "DHCP request"];
      Neutron -> Node [label = "next-server = Conductor"];
      Node -> Conductor [label = "Attempts to tftpboot from Conductor"];
      "TFTP/HTTPd" -> Node [label = "Send deploy kernel, ramdisk and config"];
      Node -> Node [label = "Runs agent\nramdisk"];
      Node -> API [label = "lookup()"];
      API -> Conductor [label = "..."];
      Conductor -> Node [label = "Pass UUID"];
      Node -> API [label = "Heartbeat (UUID)"];
      API -> Conductor [label = "Heartbeat"];
      Conductor -> Node [label = "Continue deploy: Pass image, disk info"];
      Node -> Node [label = "Exposes disks\nvia iSCSI"];
      Conductor -> Node [label = "iSCSI attach"];
      Conductor -> Node [label = "Copies user image"];
      Conductor -> Node [label = "iSCSI detach"];
      Conductor -> Conductor [label = "Mark node as\nACTIVE"];
      Conductor -> Neutron [label = "Clear DHCPBOOT"];
      Conductor -> Node [label = "Reboot"];
      Node -> Node [label = "Reboots into\nuser instance"];
   }

(From a `talk`_  and `slides`_)

Example 2: PXE Boot and Direct Deploy Process
---------------------------------------------

This process is used with agent_* family of drivers.

.. seqdiag::
   :scale: 80
   :alt: pxe_ipmi_agent

   diagram {
      Nova; API; Conductor; Neutron; "TFTP/HTTPd"; Node;
      activation = none;
      edge_length = 250;
      span_height = 1;
      default_note_color = white;
      default_fontsize = 14;

      Nova -> API [label = "Set instance_info", note = "image_source\n,root_gb,etc."];
      Nova -> API [label = "Set provision_state"];
      API -> Conductor [label = "do_node_deploy()"];
      Conductor -> Conductor [label = "Cache images"];
      Conductor -> Conductor [label = "Update pxe,\ntftp configs"];
      Conductor -> Neutron [label = "Update DHCPBOOT"];
      Conductor -> Node [label = "power on"];
      Node -> Neutron [label = "DHCP request"];
      Neutron -> Node [label = "next-server = Conductor"];
      Node -> Conductor [label = "Attempts tftpboot"];
      "TFTP/HTTPd" -> Node [label = "Send deploy kernel, ramdisk and config"];
      Node -> Node [label = "Runs agent\nramdisk"];
      Node -> API [label = "lookup()"];
      API -> Conductor [label = "..."];
      Conductor -> Node [label = "Pass UUID"];
      Node -> API [label = "Heartbeat (UUID)"];
      API -> Conductor [label = "Heartbeat"];
      Conductor -> Node [label = "Continue deploy: Pass image, disk info"];
      === Node downloads image, writes to disk ===
      Node -> API [label = "Heartbeat periodically"];
      API -> Conductor [label = "..."];
      Conductor -> Node [label = "Is deploy done yet?"];
      Node -> Conductor [label = "Still working..."];
      === When deploy is done ===
      Conductor -> Neutron [label = "Clear DHCPBOOT"];
      Conductor -> Node [label = "Set bootdev HDD"];
      Conductor -> Node [label = "Reboot"];
      Node -> Node [label = "Reboots into\nuser instance"];
   }

(From a `talk`_  and `slides`_)

.. _talk: https://www.openstack.org/summit/vancouver-2015/summit-videos/presentation/isn-and-039t-it-ironic-the-bare-metal-cloud
.. _slides: http://devananda.github.io/talks/isnt-it-ironic.html
