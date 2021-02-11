
Using Bare Metal service as a standalone service
================================================

Service settings
----------------

It is possible to use the Bare Metal service without other OpenStack services.
You should make the following changes to ``/etc/ironic/ironic.conf``:

#. Choose an authentication strategy which supports standalone, one option is
   ``noauth``::

    [DEFAULT]
    ...
    auth_strategy=noauth

   Another option is ``http_basic`` where the credentials are stored in an
   `Apache htpasswd format`_ file::

    [DEFAULT]
    ...
    auth_strategy=http_basic
    http_basic_auth_user_file=/etc/ironic/htpasswd

   Only the ``bcrypt`` format is supported, and the Apache `htpasswd` utility can
   be used to populate the file with entries, for example::

    htpasswd -nbB myName myPassword >> /etc/ironic/htpasswd

#. If you want to disable the Networking service, you should have your network
   pre-configured to serve DHCP and TFTP for machines that you're deploying.
   To disable it, change the following lines::

    [dhcp]
    ...
    dhcp_provider=none

   .. note::
      If you disabled the Networking service and the driver that you use is
      supported by at most one conductor, PXE boot will still work for your
      nodes without any manual config editing. This is because you know all
      the DHCP options that will be used for deployment and can set up your
      DHCP server appropriately.

      If you have multiple conductors per driver, it would be better to use
      Networking since it will do all the dynamically changing configurations
      for you.

#. If you want to disable using a messaging broker between conductor and API
   processes, switch to JSON RPC instead:

   .. code-block:: ini

      [DEFAULT]
      rpc_transport = json-rpc

   JSON RPC also has its own authentication strategy. If it is not specified then
   the stategy defaults to ``[DEFAULT]``  ``auth_strategy``. The following will
   set JSON RPC to ``noauth``:

   .. code-block:: ini

    [json_rpc]
    auth_strategy = noauth

   For ``http_basic`` the conductor server needs a credentials file to validate
   requests:

   .. code-block:: ini

    [json_rpc]
    auth_strategy = http_basic
    http_basic_auth_user_file = /etc/ironic/htpasswd-json-rpc

   The API server also needs client-side credentials to be specified:

   .. code-block:: ini

    [json_rpc]
    auth_type = http_basic
    username = myName
    password = myPassword

Preparing images
----------------

If you don't use Image service, it's possible to provide images to Bare Metal
service via a URL.

At the moment, only two types of URLs are acceptable instead of Image
service UUIDs: HTTP(S) URLs (for example, "http://my.server.net/images/img")
and file URLs (file:///images/img).

There are however some limitations for different hardware interfaces:

* If you're using :ref:`direct-deploy` with HTTP(s) URLs, you have to provide
  the Bare Metal service with the a checksum of your instance image.

  MD5 is used by default for backward compatibility reasons. To compute an MD5
  checksum, you can use the following command::

   $ md5sum image.qcow2
   ed82def8730f394fb85aef8a208635f6  image.qcow2

  Alternatively, use a SHA256 checksum or any other algorithm supported by
  the Python's hashlib_, e.g.::

   $ sha256sum image.qcow2
   9f6c942ad81690a9926ff530629fb69a82db8b8ab267e2cbd59df417c1a28060  image.qcow2

* :ref:`direct-deploy` started supporting ``file://`` images in the Victoria
  release cycle, before that only HTTP(s) had been supported.

  .. warning::
     File images must be accessible to every conductor! Use a shared file
     system if you have more than one conductor. The ironic CLI tool will not
     transfer the file from a local machine to the conductor(s).

.. note::
   The Bare Metal service tracks content changes for non-Glance images by
   checking their modification date and time. For example, for HTTP image,
   if 'Last-Modified' header value from response to a HEAD request to
   "http://my.server.net/images/deploy.ramdisk" is greater than cached image
   modification time, Ironic will re-download the content. For "file://"
   images, the file system modification time is used.

.. _hashlib: https://docs.python.org/3/library/hashlib.html

Using CLI
---------

To use the
:python-ironicclient-doc:`baremetal CLI <cli/osc_plugin_cli.html>`,
set up these environment variables. If the ``noauth`` authentication strategy is
being used, the value ``none`` must be set for OS_AUTH_TYPE. OS_ENDPOINT is
the URL of the ironic-api process.
For example::

 export OS_AUTH_TYPE=none
 export OS_ENDPOINT=http://localhost:6385/

If the ``http_basic`` authentication strategy is being used, the value
``http_basic`` must be set for OS_AUTH_TYPE. For example::

 export OS_AUTH_TYPE=http_basic
 export OS_ENDPOINT=http://localhost:6385/
 export OS_USERNAME=myUser
 export OS_PASSWORD=myPassword

Enrolling nodes
---------------

#. Create a node in Bare Metal service. At minimum, you must specify the driver
   name (for example, ``ipmi``). You can also specify all the required
   driver parameters in one command. This will return the node UUID::

    baremetal node create --driver ipmi \
        --driver-info ipmi_address=ipmi.server.net \
        --driver-info ipmi_username=user \
        --driver-info ipmi_password=pass \
        --driver-info deploy_kernel=file:///images/deploy.vmlinuz \
        --driver-info deploy_ramdisk=http://my.server.net/images/deploy.ramdisk

    +--------------+--------------------------------------------------------------------------+
    | Property     | Value                                                                    |
    +--------------+--------------------------------------------------------------------------+
    | uuid         | be94df40-b80a-4f63-b92b-e9368ee8d14c                                     |
    | driver_info  | {u'deploy_ramdisk': u'http://my.server.net/images/deploy.ramdisk',       |
    |              | u'deploy_kernel': u'file:///images/deploy.vmlinuz', u'ipmi_address':     |
    |              | u'ipmi.server.net', u'ipmi_username': u'user', u'ipmi_password':         |
    |              | u'******'}                                                               |
    | extra        | {}                                                                       |
    | driver       | ipmi                                                                     |
    | chassis_uuid |                                                                          |
    | properties   | {}                                                                       |
    +--------------+--------------------------------------------------------------------------+

   Note that here deploy_kernel and deploy_ramdisk contain links to
   images instead of Image service UUIDs.

#. As in case of Compute service, you can also provide ``capabilities`` to node
   properties, but they will be used only by Bare Metal service (for example,
   boot mode). Although you don't need to add properties like ``memory_mb``,
   ``cpus`` etc. as Bare Metal service will require UUID of a node you're
   going to deploy.

#. Then create a port to inform Bare Metal service of the network interface
   cards which are part of the node by creating a port with each NIC's MAC
   address. In this case, they're used for naming of PXE configs for a node::

    baremetal port create $MAC_ADDRESS --node $NODE_UUID

Populating instance_info
------------------------

#. You also need to specify image information in the node's ``instance_info``
   (see :doc:`creating-images`):

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

   For example::

    baremetal node set $NODE_UUID \
        --instance-info image_source=$IMG \
        --instance-info image_checksum=$MD5HASH \
        --instance-info kernel=$KERNEL \
        --instance-info ramdisk=$RAMDISK \
        --instance-info root_gb=10

   With a SHA256 hash::

    baremetal node set $NODE_UUID \
        --instance-info image_source=$IMG \
        --instance-info image_os_hash_algo=sha256 \
        --instance-info image_os_hash_value=$SHA256HASH \
        --instance-info kernel=$KERNEL \
        --instance-info ramdisk=$RAMDISK \
        --instance-info root_gb=10

   With a whole disk image::

    baremetal node set $NODE_UUID \
        --instance-info image_source=$IMG \
        --instance-info image_checksum=$MD5HASH

#. When using low RAM nodes with ``http://`` images that are not in the RAW
   format, you may want them cached locally, converted to raw and served from
   the conductor's HTTP server::

    baremetal node set $NODE_UUID \
        --instance-info image_download_source=local

#. :ref:`Boot mode <boot_mode_support>` can be specified per instance::

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

#. To override the :ref:`boot option <local-boot-partition-images>` used for
   this instance, set the ``boot_option`` capability::

    baremetal node set $NODE_UUID \
        --instance-info capabilities='{"boot_option": "local"}'

#. Starting with the Ussuri release, you can set :ref:`root device hints
   <root-device-hints>` per instance::

    baremetal node set $NODE_UUID \
        --instance-info root_device='{"wwn": "0x4000cca77fc4dba1"}'

   This setting overrides any previous setting in ``properties`` and will be
   removed on undeployment.

#. For iLO drivers, fields that should be provided are:

   * ``ilo_deploy_iso`` under ``driver_info``;

   * ``ilo_boot_iso``, ``image_source``, ``root_gb`` under ``instance_info``.

#. For software RAID with whole-disk images, the root UUID of the root
   partition has to be provided so that the bootloader can be correctly
   installed::

    baremetal node set $NODE_UUID \
        --instance-info image_rootfs_uuid=<uuid>

Deployment
----------

#. Validate that all parameters are correct::

    baremetal node validate $NODE_UUID

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

#. Now you can start the deployment, run::

    baremetal node deploy $NODE_UUID


Ramdisk booting
---------------

Advanced operators, specifically ones working with ephemeral workloads,
may find it more useful to explicitly treat a node as one that would always
boot from a Ramdisk.

This functionality is largely intended for network booting, however some
other boot interface, such as the ``redfish-virtual-media`` support enabling
the same basic functionality through the existing interfaces.

To use, a few different settings must be modified.

#. Change the ``deploy_interface`` on the node to ``ramdisk``::

       baremetal node set $NODE_UUID \
               --deploy-interface ramdisk

#. Set a kernel and ramdisk to be utilized::

       baremetal node set $NODE_UUID \
               --instance-info kernel=$KERNEL_URL \
               --instance-info ramdisk=$RAMDISK_URL

#. Deploy the node::

       baremetal node deploy $NODE_UUID

   .. warning::
      Configuration drives, also known as a configdrive, is not supported
      with the ``ramdisk`` deploy interface. Please ensure your ramdisk
      CPIO archive contains all necessary configuration and credentials.
      This is as no disk image is written to the disk of the node being
      provisioned with a ramdisk.

The node ramdisk components will then be assembled by the conductor,
appropriate configuration put in place, and the node will then be powered
on. From there, normal node booting will occur. Upon undeployment of the node,
normal cleaning proceedures will occur as configured with-in the conductor.

Ramdisk booting with ISO media
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Currently supported for the use of ramdisks with the ``redfish-virtual-media``
and ``ipxe`` boot interfaces, an operator may request an explict ISO file to
be booted.

#. Store the URL to the ISO image to ``instance_info/boot_iso``,
   instead of a ``kernel`` or ``ramdisk`` setting::

       baremetal node set $NODE_UUID \
               --instance-info boot_iso=$BOOT_ISO_URL

#. Deploy the node::

          baremetal node deploy $NODE_UUID


.. warning::
   This feature, when utilized with the ``ipxe`` ``boot_interface``,
   will only allow a kernel and ramdisk to be booted from the
   supplied ISO file. Any additional contents, such as additional
   ramdisk contents or installer package files will be unavailable
   after the boot of the Operating System. Operators wishing to leverage
   this functionality for actions such as OS installation should explore
   use of the standard ``ramdisk`` ``deploy_interface`` along with the
   ``instance_info/kernel_append_params`` setting to pass arbitrary
   settings such as a mirror URL for the initial ramdisk to load data from.
   This is a limitation of iPXE and the overall boot process of the
   operating system where memory allocated by iPXE is released.


Other references
----------------

* :ref:`local-boot-without-compute`

.. _`Apache htpasswd format`: https://httpd.apache.org/docs/current/misc/password_encryptions.html
