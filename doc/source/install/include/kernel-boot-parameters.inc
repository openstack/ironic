.. _kernel-boot-parameters:

Appending kernel parameters to boot instances
---------------------------------------------

The Bare Metal service supports passing custom kernel parameters to boot instances to fit
users' requirements. The way to append the kernel parameters is depending on how to boot instances.


Network boot
~~~~~~~~~~~~

Currently, the Bare Metal service supports assigning unified kernel parameters to PXE
booted instances by:

* Modifying the ``[pxe]/kernel_append_params`` configuration option, for
  example:

  .. code-block:: ini

    [pxe]
    kernel_append_params = quiet splash

  .. note::
     The option was called ``pxe_append_params`` before the Xena cycle.

* Copying a template from shipped templates to another place, for example::

    https://opendev.org/openstack/ironic/src/branch/master/ironic/drivers/modules/pxe_config.template

  Making the modifications and pointing to the custom template via the configuration
  options: ``[pxe]/pxe_config_template`` and ``[pxe]/uefi_pxe_config_template``.


Local boot
~~~~~~~~~~

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


Console
~~~~~~~

In order to change default console configuration in the Bare Metal
service configuration file (``[pxe]`` section in ``/etc/ironic/ironic.conf``),
include the serial port terminal and serial speed. Serial speed must be
the same as the serial configuration in the BIOS settings, so that the
operating system boot process can be seen in the serial console or web console.
Following examples represent possible parameters for serial and web console
respectively.

* Node serial console. The console parameter ``console=ttyS0,115200n8``
  uses ``ttyS0`` for console output at ``115200bps, 8bit, non-parity``, e.g.::

        [pxe]

        # Additional append parameters for baremetal PXE boot.
        kernel_append_params = nofb nomodeset vga=normal console=ttyS0,115200n8


* For node web console configuration is similar with the addition of ``ttyX``
  parameter, see example::

        [pxe]

        # Additional append parameters for baremetal PXE boot.
        kernel_append_params = nofb nomodeset vga=normal console=tty0 console=ttyS0,115200n8

For detailed information on how to add consoles see the reference documents
`kernel params`_ and `serial console`_.
In case of local boot the Bare Metal service is not able to control kernel boot
parameters.  To configure console locally, follow 'Local boot' section above.

.. _`kernel params`: https://www.kernel.org/doc/html/latest/admin-guide/kernel-parameters.html
.. _`serial console`: https://www.kernel.org/doc/html/latest/admin-guide/serial-console.html
