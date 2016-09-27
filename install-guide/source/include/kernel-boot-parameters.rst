.. _kernel-boot-parameters:

Appending kernel parameters to boot instances
---------------------------------------------

The Bare Metal service supports passing custom kernel parameters to boot instances to fit
users' requirements. The way to append the kernel parameters is depending on how to boot instances.


Network boot
============

Currently, the Bare Metal service supports assigning unified kernel parameters to PXE
booted instances by:

* Modifying the ``[pxe]/pxe_append_params`` configuration option, for example::

    [pxe]

    pxe_append_params = quiet splash

* Copying a template from shipped templates to another place, for example::

    https://git.openstack.org/cgit/openstack/ironic/tree/ironic/drivers/modules/pxe_config.template?stable%2Fnewton

  Making the modifications and pointing to the custom template via the configuration
  options: ``[pxe]/pxe_config_template`` and ``[pxe]/uefi_pxe_config_template``.


Local boot
==========

For local boot instances, users can make use of configuration drive
(see :ref:`configdrive`) to pass a custom
script to append kernel parameters when creating an instance. This is more
flexible and can vary per instance.
Here is an example for grub2 with ubuntu, users can customize it
to fit their use case:

    .. code:: python

     #!/usr/bin/env python
     import os

     # Default grub2 config file in Ubuntu
     grub_file = '/etc/default/grub'
     # Add parameters here to pass to instance.
     kernel_parameters = ['quiet', 'splash']
     grub_cmd = 'GRUB_CMDLINE_LINUX'
     old_grub_file = grub_file+'~'
     os.rename(grub_file, old_grub_file)
     cmdline_existed = False
     with open(grub_file, 'w') as writer, \
            open(old_grub_file, 'r') as reader:
            for line in reader:
                key = line.split('=')[0]
                if key == grub_cmd:
                    #If there is already some value:
                    if line.strip()[-1] == '"':
                        line = line.strip()[:-1] + ' ' + ' '.join(kernel_parameters) + '"'
                    cmdline_existed = True
                writer.write(line)
            if not cmdline_existed:
                line = grub_cmd + '=' + '"' + ' '.join(kernel_parameters) + '"'
                writer.write(line)

     os.remove(old_grub_file)
     os.system('update-grub')
     os.system('reboot')
