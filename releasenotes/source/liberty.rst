============================================
Liberty Series (4.0.0 - 4.2.5) Release Notes
============================================

.. release-notes::
   :branch: origin/stable/liberty
   :earliest-version: 4.2.2

.. _V4-2-1:

4.2.1
=====

This release is a patch release on top of 4.2.0, as part of the stable
Liberty series. Full details are available on Launchpad:
https://launchpad.net/ironic/liberty/4.2.1.

* Import Japanese translations - our first major translation addition!

* Fix a couple of locale issues with deployments, when running on a system
  using the Japanese locale

.. _V4-2-0:

4.2.0
=====

This release is proposed as the stable Liberty release for Ironic, and brings
with it some bug fixes and small features. Full release details are available
on Launchpad: https://launchpad.net/ironic/liberty/4.2.0.

* Deprecated the bash ramdisk

  The older bash ramdisk built by diskimage-builder is now deprecated and
  support will be removed at the beginning of the "N" development cycle. Users
  should migrate to a ramdisk running ironic-python-agent, which now also
  supports the pxe_* drivers that the bash ramdisk was responsible for.
  For more info on building an ironic-python-agent ramdisk, see:
  https://docs.openstack.org/developer/ironic/deploy/install-guide.html#building-or-downloading-a-deploy-ramdisk-image

* Raised API version to 1.14

  * 1.12 allows setting RAID properties for a node; however support for
    putting this configuration on a node is not yet implemented for in-tree
    drivers; this will be added in a future release.

  * 1.13 adds a new 'abort' verb to the provision state API. This may be used
    to abort cleaning for nodes in the CLEANWAIT state.

  * 1.14 makes the following endpoints discoverable in the API:

    * /v1/nodes/<UUID or logical name>/states

    * /v1/drivers/<driver name>/properties

* Implemented a new Boot interface for drivers

  This change enhances the driver interface for driver authors, and should not
  affect users of Ironic, by splitting control of booting a server from the
  DeployInterface. The BootInterface is responsible for booting an image on a
  server, while the DeployInterface is responsible for deploying a tenant image
  to a server.

  This has been implemented in most in-tree drivers, and is a
  backwards-compatible change for out-of-tree drivers. The following in-tree
  drivers will be updated in a forth-coming release:

  * agent_ilo

  * agent_irmc

  * iscsi_ilo

  * iscsi_irmc

* Implemented a new RAID interface for drivers

  This change enhances the driver interface for driver authors. Drivers may
  begin implementing this interface to support RAID configuration for nodes.
  This is not yet implemented for any in-tree drivers.

* Image size is now checked before deployment with agent drivers

  The agent must download the tenant image in full before writing it to disk.
  As such, the server being deployed must have enough RAM for running the
  agent and storing the image. This is now checked before Ironic tells the
  agent to deploy an image. An optional config [agent]memory_consumed_by_agent
  is provided. When Ironic does this check, this config option may be set to
  factor in the amount of RAM to reserve for running the agent.

* Added Cisco IMC driver

  This driver supports managing Cisco UCS C-series servers through the
  CIMC API, rather than IPMI. Documentation is available at:
  https://docs.openstack.org/developer/ironic/drivers/cimc.html

* iLO virtual media drivers can work without Swift

  iLO virtual media drivers (iscsi_ilo and agent_ilo) can work standalone
  without Swift, by configuring an HTTP(S) server for hosting the
  deploy/boot images. A web server needs to be running on every conductor
  node and needs to be configured in ironic.conf.

  iLO driver documentation is available at:
  https://docs.openstack.org/developer/ironic/drivers/ilo.html

Known issues
~~~~~~~~~~~~

* Out of tree drivers may be broken by this release. The AgentDeploy and
  ISCSIDeploy (formerly known as PXEDeploy) classes now depend on drivers to
  utilize an instance of a BootInterface. For drivers that exist out of tree,
  that use these deploy classes, an error will be thrown during
  deployment. There is a simple fix. For drivers that expect these deploy
  classes to handle PXE booting, one can add the following code to the driver's
  `__init__` method::

    from ironic.drivers.modules import pxe

    class YourDriver(...):
        def __init__(self):
            # ...
            self.boot = pxe.PXEBoot()

  A driver that handles booting itself (for example, a driver that implements
  booting from virtual media) should use the following to make calls to the boot
  interface a no-op::

    from ironic.drivers.modules import fake

    class YourDriver(...)
        def __init__(self):
            # ...
            self.boot = fake.FakeBoot()

  Additionally, as mentioned before, `ironic.drivers.modules.pxe.PXEDeploy`
  has moved to `ironic.drivers.modules.iscsi_deploy.ISCSIDeploy`, which will
  break drivers that use this class.

  The Ironic team apologizes profusely for this inconvenience.

.. _V4-1-0:

4.1.0
=====

This brings some bug fixes and small features on top of Ironic 4.0.0.
Major changes are listed below, and full release details are available
on Launchpad: https://launchpad.net/ironic/liberty/4.1.0.

* Added CORS support

  The Ironic API now has support for CORS requests, that may be used by,
  for example, web browser-based clients. This is configured in the [cors]
  section of ironic.conf.

* Removed deprecated 'admin_api' policy rule

* Deprecated the 'parallel' option to periodic task decorator

.. _V4-0-0:

4.0.0   First semver release
============================

This is the first semver-versioned release of Ironic, created during the
OpenStack "Liberty" development cycle.  It marks a pivot in our
versioning schema from date-based versioning; the previous released
version was 2015.1. Full release details are available on Launchpad:
https://launchpad.net/ironic/liberty/4.0.0.

* Raised API version to 1.11

 - v1.7 exposes a new 'clean_step' property on the Node resource.
 - v1.8 and v1.9 improve query and filter support
 - v1.10 fixes Node logical names to support all `RFC 3986`_ unreserved
   characters
 - v1.11 changes the default state of newly created Nodes from AVAILABLE to
   ENROLL

* Support for the new ENROLL workflow during Node creation

  Previously, all Nodes were created in the "available" provision state - before
  management credentials were validated, hardware was burned in, etc. This could
  lead to workloads being scheduled to Nodes that were not yet ready for it.

  Beginning with API v1.11, newly created Nodes begin in the ENROLL state,
  and must be "managed" and "provided" before they are made available for
  provisioning. API clients must be updated to handle the new workflow when they
  begin sending the X-OpenStack-Ironic-API-Version header with a value >= 1.11.

* Migrations from Nova "baremetal" have been removed

  After a deprecation period, the scripts and support for migrating from
  the old Nova "baremetal" driver to the new Nova "ironic" driver have
  been removed from Ironic's tree.

* Removal of deprecated vendor driver methods

  A new @passthru decorator was introduced to the driver API in a previous
  release. In this release, support for vendor_passthru and
  driver_vendor_passthru methods has been removed. All in-tree drivers have
  been updated. Any out of tree drivers which did not update to the
  @passthru decorator during the previous release will need to do so to be
  compatible with this release.

* Introduce new BootInterface to the Driver API

  Drivers may optionally add a new BootInterface. This is merely a
  refactoring of the Driver API to support future improvements.

* Several hardware drivers have been added or enhanced

 - Add OCS Driver
 - Add UCS Driver
 - Add Wake-On-Lan Power Driver
 - ipmitool driver supports IPMI v1.5
 - Add support to SNMP driver for "APC MasterSwitchPlus" series PDU's
 - pxe_ilo driver now supports UEFI Secure Boot (previous releases of the
   iLO driver only supported this for agent_ilo and iscsi_ilo)
 - Add Virtual Media support to iRMC Driver
 - Add BIOS config to DRAC Driver
 - PXE drivers now support GRUB2

.. _`RFC 3986`: https://www.ietf.org/rfc/rfc3986.txt
