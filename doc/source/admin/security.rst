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

.. WARNING::
   This information is presently in flux as of the Wallaby release with the
   implementation of ``Secure RBAC`` where ``system`` and ``project``
   scoped requests are able to be parsed and default access controls support
   a delineation of roles and responsibilities through the roles.
   Please see :doc:`/admin/secure-rbac`.

Beginning with the Newton (6.1.0) release, the Bare Metal service allows
operators significant control over API access:

* Access may be restricted to each method (GET, PUT, etc) for each
  REST resource. Defaults are provided with the release and defined in code.
* Access may be divided between an "administrative" role with full access and
  "observer" role with read-only access. By default, these roles are assigned
  the names ``baremetal_admin`` and ``baremetal_observer``, respectively.
* By default, passwords and instance secrets are hidden in ``driver_info`` and
  ``instance_info``, respectively. In case of debugging or diagnosing, the
  behavior can be overridden by changing the policy file. To allow password
  in ``driver_info`` unmasked for users with administrative privileges, apply
  following changes to policy configuration file::

    "show_password": "rule:is_admin"

  And restart the Bare Metal API service to take effect. Please check
  :doc:`/configuration/policy` for more details.

Prior to the Newton (6.1.0) release, the Bare Metal service only supported two
policy options:

* API access may be secured by a simple policy rule: users with administrative
  privileges may access all API resources, whereas users without administrative
  privileges may only access public API resources.
* Passwords contained in the ``driver_info`` field may be hidden from all API
  responses with the ``show_password`` policy setting. This defaults to always
  hide passwords, regardless of the user's role. You can override it with
  policy configuration as described above.


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

Some hardware types support turning `UEFI secure boot`_ dynamically when
deploying an instance. Currently these are :doc:`/admin/drivers/ilo`,
:doc:`/admin/drivers/irmc` and :doc:`/admin/drivers/redfish`.

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

Use element ``ubuntu-signed`` or ``fedora`` to build signed deploy ISO and
user images with `diskimage-builder
<https://pypi.org/project/diskimage-builder>`_.

The below command creates files named cloud-image-boot.iso, cloud-image.initrd,
cloud-image.vmlinuz and cloud-image.qcow2 in the current working directory::

 cd <path-to-diskimage-builder>
 ./bin/disk-image-create -o cloud-image ubuntu-signed baremetal iso

Ensure the public key of the signed image is loaded into bare metal to deploy
signed images.

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
Compute), you need to add the capability directly to the node's
``instance_info``::

  baremetal node set <node> --instance-info capabilities='{"secure_boot": "true"}'

.. _UEFI secure boot: https://en.wikipedia.org/wiki/Unified_Extensible_Firmware_Interface#Secure_boot

Other considerations
====================

Internal networks
-----------------

Access to networks which the Bare Metal service uses internally should be
prohibited from outside. These networks are the ones used for management (with
the nodes' BMC controllers), provisioning, cleaning (if used) and rescuing
(if used).

This can be done with physical or logical network isolation, traffic filtering, etc.

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

There are `two (unauthorized) endpoints
<https://docs.openstack.org/api-ref/baremetal/#utility>`_ in the
Bare Metal API that are intended for use by the ironic-python-agent RAM disk.
They are not intended for public use.

These endpoints can potentially cause security issues. Access to
these endpoints from external or untrusted networks should be prohibited.
An easy way to do this is to:

* set up two groups of API services: one for external requests, the second for
  deploy RAM disks' requests.
* to disable unauthorized access to these endpoints in the (first) API services
  group that serves external requests, the following lines should be
  added to the
  :ironic-doc:`policy.yaml file <configuration/sample-policy.html>`::

    # Send heartbeats from IPA ramdisk
    "baremetal:node:ipa_heartbeat": "rule:is_admin"

    # Access IPA ramdisk functions
    "baremetal:driver:ipa_lookup": "rule:is_admin"
