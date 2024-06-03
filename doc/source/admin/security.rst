.. _security:

=================
Security Overview
=================

While the Bare Metal service is intended to be a secure application, it is
important to understand what it does and does not cover today.

Deployers must properly evaluate their use case and take the appropriate
actions to secure their environment(s). This document is intended to provide an
overview of what risks an operator of the Bare Metal service should be aware
of. It is not intended as a How-To guide for securing a data center or an
OpenStack deployment.

.. TODO: add "Security Considerations for Network Boot" section

.. TODO: add "Credential Storage and Management" section

.. TODO: add "Multi-tenancy Considerations" section


REST API: user roles and policy settings
========================================

By default, users are authenticated and authorization details are provided to
Ironic as part web API's operating security model and interaction with
keystone.

Default REST API user roles and policy settings have evolved, starting in the
Wallaby development cycle, into a model often referred to in the OpenStack
community as ``Secure RBAC``. This model is intended balance usability, while
leaning towards a secure-by-default state. You can find more information on
this at :doc:`/admin/secure-rbac`.

Operators may choose to override default, in-code, Role Based Access Control
policies by utilizing override policies, which you can learn about at
:doc:`/configuration/policy`.

Conductor Operation
-------------------

Ironic relies upon the REST API to validate, authenticate, and authorize user
requests and interactions. While the conductor service *can* be operated with
the REST API in a single process, the normal operating mode is as separate
services either connected to a Message bus or use of an authenticated JSON-RPC
endpoint.

Multi-tenancy
=============

There are two aspects of multitenancy to consider when evaluating a deployment
of the Bare Metal Service: interactions between tenants on the network, and
actions one tenant can take on a machine that will affect the next tenant.

Network Interactions
--------------------

Interactions between tenants' workloads running simultaneously on separate
servers include, but are not limited to: IP spoofing, packet sniffing, and
network man-in-the-middle attacks.

By default, the Bare Metal service provisions all nodes on a "flat" network, and
does not take any precautions to avoid or prevent interaction between tenants.
This can be addressed by integration with the OpenStack Identity, Compute, and
Networking services, so as to provide tenant-network isolation. Additional
documentation on `network multi-tenancy <multitenancy>`_ is available.

Lingering Effects
-----------------
Interactions between tenants placed sequentially on the same server include, but
are not limited to: changes in BIOS settings, modifications to firmware, or
files left on disk or peripheral storage devices (if these devices are not
erased between uses).

By default, the Bare Metal service will erase (clean) the local disk drives
during the "cleaning" phase, after deleting an instance. It *does not* reset
BIOS or reflash firmware or peripheral devices. This can be addressed through
customizing the utility ramdisk used during the "cleaning" phase. See details in
the `Firmware security`_ section.


Firmware security
=================

When the Bare Metal service deploys an operating system image to a server, that
image is run natively on the server without virtualization. Any user with
administrative access to the deployed instance has administrative access to
the underlying hardware.

Most servers' default settings do not prevent a privileged local user from
gaining direct access to hardware devices.  Such a user could modify device or
firmware settings, and potentially flash new firmware to the device, before
deleting their instance and allowing the server to be allocated to another
user.

If the ``[conductor]/automated_clean`` configuration option is enabled (and
the ``[deploy]/erase_devices_priority`` configuration option is not zero),
the Bare Metal service will securely erase all local disk devices within a
machine during instance deletion. However, the service does not ship with
any code that will validate the integrity of, or make any modifications to,
system or device firmware or firmware settings.

Operators are encouraged to write their own hardware manager plugins for the
``ironic-python-agent`` ramdisk.  This should include custom ``clean steps``
that would be run during the :ref:`cleaning` process, as part of Node
de-provisioning. The ``clean steps``
would perform the specific actions necessary within that environment to ensure
the integrity of each server's firmware.

Ideally, an operator would work with their hardware vendor to ensure that
proper firmware security measures are put in place ahead of time. This could
include:

- installing signed firmware for BIOS and peripheral devices
- using a TPM (Trusted Platform Module) to validate signatures at boot time
- booting machines in `UEFI secure boot mode`_, rather than BIOS mode, to
  validate kernel signatures
- disabling local (in-band) access from the host OS to the management controller (BMC)
- disabling modifications to boot settings from the host OS

Additional references:

- :ref:`cleaning`

.. _secure-boot:

UEFI secure boot mode
=====================

Secure Boot is an interesting topic because exists at an intersection of
hardware, security, vendors, and what you are willing to put in place to in
terms of process, controls, or further mechanisms to enable processes and
capabilities.

At a high level, Secure Boot is where an artifact such as an operating system
kernel or Preboot eXecution Environment (PXE) binary is read by the UEFI
firmware, and executed if the artifact is signed with a trusted key.
Once a piece of code has been loaded and executed, it may read more bytecode
in and verify additional signed artifacts which were signed utilizing
different keys.

This is fundamentally how most Linux operating systems boot today. A ``shim``
loader is signed by an authority, Microsoft, which is generally trusted by
hardware vendors. The shim loader then loads a boot loader such as Grub, which
then loads an operating system.

Underlying challenges
---------------------

A major challenge for Secure Boot is the state of Preboot eXecution
Environment binaries. Operating System distribution vendors tend not to
request the authority with the general signing keys to sign these binary
artifacts. The result of this, is that it is nearly impossible to network
boot a machine which has Secure Boot enabled.

There are reports in the Open Source community that Microsoft has been willing
to sign iPXE binaries, however the requirements are a bit steep for Open
Source and largely means that Vendors would need to shoulder the burden for
signed iPXE binaries to become common place. The iPXE developers provide
further `details on their website <https://ipxe.org/appnote/etoken>`_,
but it provides the details which solidify why we're unlikely to see
a signed iPXE loader.

That is, unless, you sign iPXE yourself.

Which you can do, but you need to put in place your own key management
infrastructure and teach the hardware to trust your signature, which is
no simple feat in itself.

.. NOTE::
   The utility to manage keys in Linux on a local machine is `mokutil`,
   however it's modeled for manual invocation. One may be able to manage
   keys via Baseboard Management Controller, and Ironic may add such
   capabilities at some point in time.

There is a possibility of utilizing
`shim <https://wiki.debian.org/SecureBoot#Shim>`_ and Grub2 to network boot
a machine, however Grub2's capabilities for booting a machine are extremely
limited when compared to a tool like iPXE. It is also worth noting the bulk
of Ironic's example configurations utilize iPXE, including whole activities
like unmanaged hardware introspection with ironic-inspector.

For extra context, unmanaged introspection is when you ask ironic-inspector
to inspect a machine *instead* of asking ironic. In other words, using
``openstack baremetal introspection start <node>`` versus
``baremetal node inspect <node>`` commands. This does require the
``[inspector]require_managed_boot`` setting be set to ``true``.

Driver support for Deployment with Secure Boot
----------------------------------------------

Some hardware types support turning `UEFI secure boot`_ dynamically when
deploying an instance. Currently these are :doc:`/admin/drivers/ilo`,
:doc:`/admin/drivers/irmc` and :doc:`/admin/drivers/redfish`.

Other drivers, such as :doc:`/admin/drivers/ipmitool`, may be able to be manually
configured on the host, but as there is not standardization of Secure Boot
support in the IPMI protocol, you may encounter unexpected behavior.

Support for the UEFI secure boot is declared by adding the ``secure_boot``
capability in the ``capabilities`` parameter in the ``properties`` field of
a node. ``secure_boot`` is a boolean parameter and takes value as ``true`` or
``false``.

To enable ``secure_boot`` on a node add it to ``capabilities``::

 baremetal node set <node> --property capabilities='secure_boot:true'

Alternatively use :doc:`/admin/inspection`  to automatically populate
the secure boot capability.

.. warning::
   UEFI secure boot only works in UEFI boot mode, see :ref:`boot_mode_support`
   for how to turn it on and off.

Compatible images
-----------------

Most mainstream and vendor backed Linux based public cloud images are already
compatible with use of secure boot.

Using Shim and Grub2 for Secure Boot
------------------------------------

To utilize Shim and Grub to boot a baremetal node, actions are required
by the administrator of the Ironic deployment as well as the user of
Ironic's API.

For the Ironic Administrator
~~~~~~~~~~~~~~~~~~~~~~~~~~~~

To enable use of grub to network boot baremetal nodes for activities such
as managed introspection, node cleaning, and deployment, some configuration
is required in ironic.conf.::

  [DEFAULT]
  enabled_boot_interfaces = pxe
  [pxe]
  uefi_pxe_config_template = $pybasedir/drivers/modules/pxe_grub_config.template
  tftp_root = /tftpboot
  loader_file_paths = bootx64.efi:/usr/lib/shimx64.efi.signed,grubx64.efi:/usr/lib/grub/x86_64-efi-signed/grubnetx64.efi.signed

.. NOTE::
   You may want to leverage the ``[pxe]loader_file_paths`` feature, which
   automatically copies boot loaders into the ``tftp_root`` folder, but this
   functionality is not required if you manually copy the named files into
   the Preboot eXecution Environment folder(s), by default the [pxe]tftp_root,
   and [deploy]http_root folders.

.. WARNING::
   Shim/Grub artifact paths will vary by distribution. The example above is
   taken from Ironic's Continuous Integration test jobs where this
   functionality is exercised.

For the Ironic user
~~~~~~~~~~~~~~~~~~~

To set a node to utilize the ``pxe`` boot_interface, execute the baremetal
command::

  baremetal node set --boot-interface pxe <node>

Alternatively, if your hardware supports HttpBoot and your Ironic is at
least 2023.2, you can set the ``http`` boot_interface instead::

  baremetal node set --boot-interface http <node>

Enabling with OpenStack Compute
-------------------------------

Nodes having ``secure_boot`` set to ``true`` may be requested by adding an
``extra_spec`` to the nova flavor::

  openstack flavor set <flavor> --property capabilities:secure_boot="true"
  openstack server create --flavor <flavor> --image <image> instance-1

If ``capabilities`` is used in ``extra_spec`` as above, nova scheduler
(``ComputeCapabilitiesFilter``) will match only ironic nodes which have
the ``secure_boot`` set appropriately in ``properties/capabilities``. It will
filter out rest of the nodes.

The above facility for matching in nova can be used in heterogeneous
environments where there is a mix of machines supporting and not supporting
UEFI secure boot, and operator wants to provide a choice to the user
regarding secure boot.  If the flavor doesn't contain ``secure_boot`` then
nova scheduler will not consider secure boot mode as a placement criteria,
hence user may get a secure boot capable machine that matches with user
specified flavors but deployment would not use its secure boot capability.
Secure boot deploy would happen only when it is explicitly specified through
flavor.

Enabling standalone
-------------------

To request secure boot for an instance in standalone mode (without OpenStack
Compute), you must explicitly inform Ironic::

  baremetal node set secure boot on <node>

Which can also be disabled by exeuting negative form of the command::

  baremetal node set secure boot off <node>

.. _UEFI secure boot: https://en.wikipedia.org/wiki/UEFI#Secure_Boot

Other considerations
====================

Internal networks
-----------------

Access to networks which the Bare Metal service uses internally should be
prohibited from outside. These networks are the ones used for management (with
the nodes' BMC controllers), provisioning, cleaning (if used) and rescuing
(if used).

This can be done with physical or logical network isolation, traffic filtering, etc.

While the Ironic project has made strives to enable the API to be utilized
by end users directly, we still encourage operators to be as mindful as
possible to ensure appropriate security controls are in place to also restrict
access to the service.

Management interface technologies
---------------------------------

Some nodes support more than one management interface technology (vendor and
IPMI for example). If you use only one modern technology for out-of-band node
access, it is recommended that you disable IPMI since the IPMI protocol is not
secure.  If IPMI is enabled, in most cases a local OS administrator is able to
work in-band with IPMI settings without specifying any credentials, as this
is a DCMI specification requirement.

Tenant network isolation
------------------------

If you use tenant network isolation, services (TFTP or HTTP) that handle the
nodes' boot files should serve requests only from the internal networks that
are used for the nodes being deployed and cleaned.

TFTP protocol does not support per-user access control at all.

For HTTP, there is no generic and safe way to transfer credentials to the
node.

Also, tenant network isolation is not intended to work with network-booting
a node by default, once the node has been provisioned.

API endpoints for RAM disk use
------------------------------

There are `three (unauthorized) endpoints
<https://docs.openstack.org/api-ref/baremetal/#utility>`_ in the
Bare Metal API that are intended for use by the ironic-python-agent RAM disk.
They are not intended for public use.

These endpoints can potentially cause security issues even though the logic
around these endpoints is intended to be defensive in nature. Access to
these endpoints from external or untrusted networks should be prohibited.
An easy way to do this is to:

* set up two groups of API services: one for external requests, the second for
  deploy RAM disks' requests.
* to disable unauthorized access to these endpoints in the (first) API services
  group that serves external requests, the following lines should be
  added to the
  :ironic-doc:`policy.yaml file <configuration/sample-policy.html>`::

    # Send heartbeats from IPA ramdisk
    "baremetal:node:ipa_heartbeat": "!"

    # Access IPA ramdisk functions
    "baremetal:driver:ipa_lookup": "!"

    # Continue introspection IPA ramdisk endpoint
    "baremetal:driver:ipa_continue_inspection": "!"

Rate Limiting
-------------

Ironic has a concept of a "concurrent action limit", which allows
operators to restrict concurrent, long running, destructive actions.

The overall use case this was implemented for was to help provide
backstop for runaway processes and actions which one may apply to
an environment, such as batch deletes of nodes. The appropriate
settings for these settings are the ``[conductor]max_concurrent_deploy``
with a default value of 250, and ``[conductor]max_concurrent_clean``
with a default value of 50. These settings are reasonable defaults
for medium to large deployments, but depending on load and usage
patterns and can be safely tuned to be in line with an operator's
comfort level.

Memory Limiting
---------------

Because users of the Ironic API can request activities which
can consume large amounts of memory, for example, disk image format
conversions as part of a deployment operations. The Ironic conductor
service has a minimum memory available check which is executed before
launching these operations. It defaults to ``1024`` Megabytes, and can
be tuned using the ``[DEFAULT]minimum_required_memory`` setting.

Operators with a higher level of concurrency may wish to increase the
default value.
