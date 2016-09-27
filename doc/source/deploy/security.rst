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

Beginning with the Newton (6.1.0) release, the Bare Metal service allows
operators significant control over API access:

* Access may be restricted to each method (GET, PUT, etc) for each
  REST resource. Defaults are provided with the release and defined in code.
* Access may be divided between an "administrative" role with full access and
  "observer" role with read-only access. By default, these roles are assigned
  the names ``baremetal_admin`` and ``baremetal_observer``, respectively.
* As before, passwords may be hidden in ``driver_info``.

Prior to the Newton (6.1.0) release, the Bare Metal service only supported two
policy options:

* API access may be secured by a simple policy rule: users with administrative
  privileges may access all API resources, whereas users without administrative
  privileges may only access public API resources.
* Passwords contained in the ``driver_info`` field may be hidden from all API
  responses with the ``show_password`` policy setting. This defaults to always
  hide passwords, regardless of the user's role.


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
that would be run during the `automated cleaning`_ process, as part of Node
de-provisioning. The ``clean steps``
would perform the specific actions necessary within that environment to ensure
the integrity of each server's firmware.

Ideally, an operator would work with their hardware vendor to ensure that
proper firmware security measures are put in place ahead of time. This could
include:

  - installing signed firmware for BIOS and peripheral devices
  - using a TPM (Trusted Platform Module) to validate signatures at boot time
  - booting machines in `UEFI Secure Boot mode`_, rather than BIOS mode, to
    validate kernel signatures
  - disabling local (in-band) access from the host OS to the management controller (BMC)
  - disabling modifications to boot settings from the host OS

Additional references:
  - `automated cleaning`_
  - `trusted boot with partition image`_
  - `UEFI Secure Boot mode`_

.. _automated cleaning: http://docs.openstack.org/developer/ironic/deploy/cleaning.html#automated-cleaning
.. _trusted boot with partition image: http://docs.openstack.org/project-install-guide/baremetal/newton/advanced.html#trusted-boot-with-partition-image
.. _UEFI Secure Boot mode: http://docs.openstack.org/developer/ironic/drivers/ilo.html?highlight=secure%20boot#uefi-secure-boot-support
