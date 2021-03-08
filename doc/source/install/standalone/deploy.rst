Deploying
=========

Populating instance_info
------------------------

Image information
~~~~~~~~~~~~~~~~~

You need to specify image information in the node's ``instance_info``
(see :doc:`../creating-images`):

* ``image_source`` - URL of the whole disk or root partition image,
  mandatory.

* ``root_gb`` - size of the root partition, required for partition images.

  .. note::
     Older versions of the Bare Metal service used to require a positive
     integer for ``root_gb`` even for whole-disk images. You may want to set
     it for compatibility.

* ``image_checksum`` - MD5 checksum of the image specified by
  ``image_source``, only required for ``http://`` images when using
  :ref:`direct-deploy`.

  .. note::
     Additional checksum support exists via the ``image_os_hash_algo`` and
     ``image_os_hash_value`` fields. They may be used instead of the
     ``image_checksum`` field.

  .. warning::
     If your operating system is running in FIPS 140-2 mode, MD5 will not be
     available, and you **must** use SHA256 or another modern algorithm.

  Starting with the Stein release of ironic-python-agent can also be a URL
  to a checksums file, e.g. one generated with:

  .. code-block:: shell

     cd /path/to/http/root
     md5sum *.img > checksums

* ``kernel``, ``ramdisk`` - HTTP(s) or file URLs of the kernel and
  initramfs of the target OS. Must be added **only** for partition images.

For example:

.. code-block:: shell

 baremetal node set $NODE_UUID \
     --instance-info image_source=$IMG \
     --instance-info image_checksum=$MD5HASH \
     --instance-info kernel=$KERNEL \
     --instance-info ramdisk=$RAMDISK \
     --instance-info root_gb=10

With a SHA256 hash:

.. code-block:: shell

 baremetal node set $NODE_UUID \
     --instance-info image_source=$IMG \
     --instance-info image_os_hash_algo=sha256 \
     --instance-info image_os_hash_value=$SHA256HASH \
     --instance-info kernel=$KERNEL \
     --instance-info ramdisk=$RAMDISK \
     --instance-info root_gb=10

With a whole disk image:

.. code-block:: shell

 baremetal node set $NODE_UUID \
     --instance-info image_source=$IMG \
     --instance-info image_checksum=$MD5HASH

.. note::
   For iLO drivers, fields that should be provided are:

   * ``ilo_deploy_iso`` under ``driver_info``;

   * ``ilo_boot_iso``, ``image_source``, ``root_gb`` under ``instance_info``.

When using low RAM nodes with ``http://`` images that are not in the RAW
format, you may want them cached locally, converted to raw and served from
the conductor's HTTP server:

.. code-block:: shell

 baremetal node set $NODE_UUID --instance-info image_download_source=local

For software RAID with whole-disk images, the root UUID of the root
partition has to be provided so that the bootloader can be correctly
installed:

.. code-block:: shell

 baremetal node set $NODE_UUID --instance-info image_rootfs_uuid=<uuid>

Capabilities
~~~~~~~~~~~~

* :ref:`Boot mode <boot_mode_support>` can be specified per instance:

  .. code-block:: shell

    baremetal node set $NODE_UUID \
        --instance-info capabilities='{"boot_mode": "uefi"}'

  Otherwise, the ``boot_mode`` capability from the node's ``properties`` will
  be used.

  .. warning::
        The two settings must not contradict each other.

  .. note::
     This capability was introduced in the Wallaby release series,
     previously ironic used a separate ``instance_info/deploy_boot_mode``
     field instead.

* To override the :ref:`boot option <local-boot-partition-images>` used for
  this instance, set the ``boot_option`` capability:

  .. code-block:: shell

    baremetal node set $NODE_UUID \
        --instance-info capabilities='{"boot_option": "local"}'

* Starting with the Ussuri release, you can set :ref:`root device hints
  <root-device-hints>` per instance:

  .. code-block:: shell

    baremetal node set $NODE_UUID \
        --instance-info root_device='{"wwn": "0x4000cca77fc4dba1"}'

  This setting overrides any previous setting in ``properties`` and will be
  removed on undeployment.

Overriding a hardware interface
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Non-admins with temporary access to a node, may wish to specify different node
interfaces. However, allowing them to set these interface values directly on
the node is problematic, as there is no automated way to ensure that the
original interface values are restored.

In order to temporarily override a hardware interface, simply set the
appropriate value in ``instance_info``. For example, if you'd like to
override a node's storage interface, run the following:

.. code-block:: shell

  baremetal node set $NODE_UUID --instance-info storage_interface=cinder

``instance_info`` values persist until after a node is cleaned.

.. note::
   This feature is available starting with the Wallaby release.

Deployment
----------

#. Validate that all parameters are correct:

   .. code-block:: console

    $ baremetal node validate $NODE_UUID
    +------------+--------+----------------------------------------------------------------+
    | Interface  | Result | Reason                                                         |
    +------------+--------+----------------------------------------------------------------+
    | boot       | True   |                                                                |
    | console    | False  | Missing 'ipmi_terminal_port' parameter in node's driver_info.  |
    | deploy     | True   |                                                                |
    | inspect    | True   |                                                                |
    | management | True   |                                                                |
    | network    | True   |                                                                |
    | power      | True   |                                                                |
    | raid       | True   |                                                                |
    | storage    | True   |                                                                |
    +------------+--------+----------------------------------------------------------------+

#. Now you can start the deployment, run:

   .. code-block:: shell

    baremetal node deploy $NODE_UUID

#. You can provide a configdrive as a JSON or as an ISO image, e.g.:

   .. code-block:: shell

    baremetal node deploy $NODE_UUID \
        --config-drive '{"meta_data": {"public_keys": {"0": "ssh key contents"}}}'

   See :doc:`/install/configdrive` for details.

#. Starting with the Wallaby release you can also request custom deploy steps,
   see :ref:`standalone-deploy-steps` for details.

Ramdisk booting
---------------

Advanced operators, specifically ones working with ephemeral workloads,
may find it more useful to explicitly treat a node as one that would always
boot from a Ramdisk. See :doc:`/admin/ramdisk-boot` for details.

Other references
----------------

* :ref:`local-boot-without-compute`
