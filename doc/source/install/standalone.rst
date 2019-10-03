
Using Bare Metal service as a standalone service
================================================

It is possible to use the Bare Metal service without other OpenStack services.
You should make the following changes to ``/etc/ironic/ironic.conf``:

#. To disable usage of Identity service tokens::

    [DEFAULT]
    ...
    auth_strategy=noauth

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

If you don't use Image service, it's possible to provide images to Bare Metal
service via a URL.

.. note::
   At the moment, only two types of URLs are acceptable instead of Image
   service UUIDs: HTTP(S) URLs (for example, "http://my.server.net/images/img")
   and file URLs (file:///images/img).

There are however some limitations for different hardware interfaces:

* If you're using :ref:`direct-deploy`, you have to provide the Bare Metal
  service with the MD5 checksum of your instance image. To compute it, you can
  use the following command::

   md5sum image.qcow2
   ed82def8730f394fb85aef8a208635f6  image.qcow2

* :ref:`direct-deploy` requires the instance image be accessible through a
  HTTP(s) URL.

Steps to start a deployment are pretty similar to those when using Compute:

#. To use the
   :python-ironicclient-doc:`openstack baremetal CLI <cli/osc_plugin_cli.html>`,
   set up these environment variables. Since no authentication strategy is
   being used, the value none must be set for OS_AUTH_TYPE. OS_ENDPOINT is
   the URL of the ironic-api process.
   For example::

    export OS_AUTH_TYPE=none
    export OS_ENDPOINT=http://localhost:6385/

#. Create a node in Bare Metal service. At minimum, you must specify the driver
   name (for example, ``ipmi``). You can also specify all the required
   driver parameters in one command. This will return the node UUID::

    openstack baremetal node create --driver ipmi \
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

    openstack baremetal port create $MAC_ADDRESS --node $NODE_UUID

#. You also need to specify some fields in the node's ``instance_info``:

   * ``image_source`` - URL of the whole disk or root partition image,
     mandatory. For :ref:`direct-deploy` only HTTP(s) links are accepted,
     while :ref:`iscsi-deploy` also accepts links to local files (prefixed
     with ``file://``).

   * ``root_gb`` - size of the root partition, required for partition images.

     .. note::
        Older versions of the Bare Metal service used to require a positive
        integer for ``root_gb`` even for whole-disk images. You may want to set
        it for compatibility.

   * ``image_checksum`` - MD5 checksum of the image specified by
     ``image_source``, only required for :ref:`direct-deploy`.

     .. note::
        Additional checksum support exists via the ``image_os_hash_algo`` and
        ``image_os_hash_value`` fields. They may be used instead of the
        ``image_checksum`` field.

     Starting with the Stein release of ironic-python-agent can also be a URL
     to a checksums file, e.g. one generated with:

     .. code-block:: shell

        cd /path/to/http/root
        md5sum *.img > checksums

   * ``kernel``, ``ramdisk`` - HTTP(s) or file URLs of the kernel and
     initramfs of the target OS, only required for partition images.

   For example::

    openstack baremetal node set $NODE_UUID \
        --instance-info image_source=$IMG \
        --instance-info image_checksum=$MD5HASH \
        --instance-info kernel=$KERNEL \
        --instance-info ramdisk=$RAMDISK \
        --instance-info root_gb=10

#. Validate that all parameters are correct::

    openstack baremetal node validate $NODE_UUID

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

    openstack baremetal node deploy $NODE_UUID

For iLO drivers, fields that should be provided are:

* ``ilo_deploy_iso`` under ``driver_info``;

* ``ilo_boot_iso``, ``image_source``, ``root_gb`` under ``instance_info``.

.. note::
   The Bare Metal service tracks content changes for non-Glance images by
   checking their modification date and time. For example, for HTTP image,
   if 'Last-Modified' header value from response to a HEAD request to
   "http://my.server.net/images/deploy.ramdisk" is greater than cached image
   modification time, Ironic will re-download the content. For "file://"
   images, the file system modification time is used.


Other references
----------------

* :ref:`local-boot-without-compute`

