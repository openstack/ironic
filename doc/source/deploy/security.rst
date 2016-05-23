.. _security:

========
Security
========

Overview
========

While Ironic is intended to be a secure application, it is important to
understand what it does and does not cover today.

Deployers must properly evaluate their use case and take the appropriate
actions to secure their environment appropriately. This document is intended to
provide an overview of what risks and operator of Ironic should be aware of. It
is not intended as a How-To guide for securing a data center or an OpenStack
deployment.

.. TODO: add "Security Considerations for Network Boot" section

.. TODO: add "Credential Storage and Management" section

.. TODO: add "Securing Ironic's REST API" section

.. TODO: add "Multi-tenancy Considerations" section

Firmware security
=================

When ironic deploys an operating system image to a server, that image is run
natively on the server without virtualization. Any user with administrative
access to the deployed instance has administrative access to the underlying
hardware.

Most servers' default settings do not prevent a privileged local user from
gaining direct access to hardware devices.  Such a user could modify device or
firmware settings, and potentially flash new firmware to the device, before
deleting their instance and allowing the server to be allocated to another
user.

If the ``automated_clean`` configuration option is enabled (previously the
``clean_nodes`` option), then Ironic will securely erase all local disk devices
within a machine during instance deletion. However, Ironic does not ship with
any code that will validate the integrity of, or make any modifications to,
system or device firmware or firmware settings.

Operators are encouraged to write their own hardware manager plugins for the
``ironic-python-agent`` ramdisk.  This should include custom ``clean steps``
that would be run as part of Node de-provisioning.  This should include custom
``clean steps`` to be run as part of the automated cleaning process, which
would perform the specific actions necessary within that environment to ensure
the integrity of each server's firmware.

Ideally, an operator would work with their hardware vendor to ensure that
proper firmware security measures are put in place ahead of time. This could
include:

  - installing signed firmware for BIOS and peripheral devices
  - using a TPM (Trusted Platform Module) to validate signatures at boot time
  - booting machines in UEFI SecureBoot mode, rather than BIOS mode, to validate
    kernel signatures
  - disabling local (in-band) access from the host OS to the management controller (BMC)
  - disabling modifications to boot settings from the host OS

Additional references:
  - http://docs.openstack.org/developer/ironic/deploy/install-guide.html?highlight=txt#trusted-boot-with-partition-image
  - http://docs.openstack.org/developer/ironic/drivers/ilo.html?highlight=secure%20boot#uefi-secure-boot-support
