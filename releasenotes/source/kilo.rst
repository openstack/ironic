===============================================
Kilo Series (2015.1.0 - 2015.1.4) Release Notes
===============================================

Features
========

State Machine
-------------

* Ironic now uses a formal model for the logical state of each node it manages (New Ironic State Machine). This has enabled the addition of two new processes: cleaning and inspection.
* Automatic disk erasure between tenants is now enabled by default. This may be extended to perform additional cleaning steps, such as re-applying firmware, resetting BIOS settings, etc (Node Cleaning).
* Both in-band and out-of-band methods are available to inspect hardware. These methods may be used to update Node properties automatically (Hardware Inspection).

Version Headers
---------------

The Ironic REST API expects a new X-OpenStack-Ironic-API-Version header be passed with each HTTP[S] request. This header allows client and server to negotiate a mutually supported interface (REST API "micro" versions). In the absence of this header, the REST service will default to a compatibility mode and yield responses compatible with Juno clients. This mode, however, prevents access to most features introduced in Kilo.

Hardware Driver Changes
=======================
The following new drivers were added:

* AMT
* iRMC
* VirtualBox (testing driver only)

The following enhancements were made to existing drivers:

* Configdrives may be used with the "agent" drivers in lieu of a metadata service, if desired.
* SeaMicro driver supports serial console
* iLO driver supports UEFI secure boot
* iLO driver supports out-of-band node inspection
* iLO driver supports resetting ilo and bios during cleaning

Support for third-party and out-of-tree drivers is enhanced by the following two changes:

* Drivers may store their own "internal" information about Nodes.
* Drivers may register their own periodic tasks to be run by the Conductor.
* vendor_passthru methods now support additional HTTP methods (eg, PUT and POST).
* vendor_passthru methods are now discoverable in the REST API. See node vendor passthru and driver vendor passthru

Other Changes
-------------

* Logical names may be used to address Nodes, in addition to their canonical UUID.
* For servers with varied local disks, hints may be supplied that affect which disk device the OS is provisioned to.
* Support for fetching kernel, ramdisk, and instance images from HTTP[S] sources directly has been added to remove the dependency on Glance. Using ironic as a standalone service
* Nodes may be placed into maintenance mode via REST API calls. An optional maintenance reason may be specified when doing so.

Known Issues
============

* Running more than one nova-compute process is not officially supported.
* While Ironic does include a ClusteredComputeManager, which allows running more than one nova-compute process with Ironic, it should be considered experimental and has many known problems.
* Drivers using the "agent" deploy mechanism do not support "rebuild --preserve-ephemeral"

Upgrade Notes
=============

* IPMI Passwords are now obfuscated in REST API responses. This may be disabled by changing API policy settings.
* The "agent" class of drivers now support both whole-disk and partition based images.
* The driver_info parameters of "pxe_deploy_kernel" and "pxe_deploy_ramdisk" are deprecated in favour of "deploy_kernel" and "deploy_ramdisk".
* Drivers implementing their own version of the vendor_passthru() method has been deprecated in favour of the new @passthru decorator.
