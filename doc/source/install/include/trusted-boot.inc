.. _trusted-boot:

Trusted boot with partition image
---------------------------------

The Bare metal service supports trusted boot with partition images.
This means at the end of the deployment process, when the node is
rebooted with the new user image, ``trusted boot`` will be performed. It will
measure the node's BIOS, boot loader, Option ROM and the Kernel/Ramdisk, to
determine whether a bare metal node deployed by Ironic should be trusted.

It's important to note that in order for this to work the node being deployed
**must** have Intel `TXT`_ hardware support. The image being deployed with
Ironic must have ``oat-client`` installed within it.

The following will describe how to enable ``trusted boot`` and boot
with PXE and Nova:

#. Create a customized user image with ``oat-client`` installed::

    disk-image-create -u fedora baremetal oat-client -o $TRUST_IMG

   For more information on creating customized images, see :ref:`image-requirements`.

#. Enable VT-x, VT-d, TXT and TPM on the node. This can be done manually through
   the BIOS. Depending on the platform, several reboots may be needed.

#. Enroll the node and update the node capability value::

    baremetal node create --driver ipmi

    baremetal node set $NODE_UUID --property capabilities={'trusted_boot':true}

#. Create a special flavor::

    nova flavor-key $TRUST_FLAVOR_UUID set 'capabilities:trusted_boot'=true

#. Prepare `tboot`_ and mboot.c32 and put them into tftp_root or http_root
   directory on all nodes with the ironic-conductor processes::

    Ubuntu:
        cp /usr/lib/syslinux/mboot.c32 /tftpboot/

    Fedora:
        cp /usr/share/syslinux/mboot.c32 /tftpboot/

   *Note: The actual location of mboot.c32 varies among different distribution versions.*

   tboot can be downloaded from
   https://sourceforge.net/projects/tboot/files/latest/download

#. Install an OAT Server. An `OAT Server`_ should be running and configured correctly.

#. Boot an instance with Nova::

    nova boot --flavor $TRUST_FLAVOR_UUID --image $TRUST_IMG --user-data $TRUST_SCRIPT trusted_instance

   *Note* that the node will be measured during ``trusted boot`` and the hash values saved
   into `TPM`_. An example of TRUST_SCRIPT can be found in `trust script example`_.

#. Verify the result via OAT Server.

   This is outside the scope of Ironic. At the moment, users can manually verify the result
   by following the `manual verify steps`_.

.. _`TXT`: http://en.wikipedia.org/wiki/Trusted_Execution_Technology
.. _`tboot`: https://sourceforge.net/projects/tboot
.. _`TPM`: http://en.wikipedia.org/wiki/Trusted_Platform_Module
.. _`OAT Server`: https://github.com/OpenAttestation/OpenAttestation/wiki
.. _`trust script example`: https://wiki.openstack.org/wiki/Bare-metal-trust#Trust_Script_Example
.. _`manual verify steps`: https://wiki.openstack.org/wiki/Bare-metal-trust#Manual_verify_result
