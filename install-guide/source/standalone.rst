
Using Bare Metal service as a standalone service
================================================

Starting with the Kilo release, it's possible to use Bare Metal service without
other OpenStack services.

You should make the following changes to ``/etc/ironic/ironic.conf``:

#. To disable usage of Identity service tokens::

    [DEFAULT]
    ...
    auth_strategy=none

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

If you don't use Image service, it's possible to provide images to Bare Metal
service via hrefs.

.. note::
   At the moment, only two types of hrefs are acceptable instead of Image
   service UUIDs: HTTP(S) hrefs (for example, "http://my.server.net/images/img")
   and file hrefs (file:///images/img).

There are however some limitations for different drivers:

* If you're using one of the drivers that use agent deploy method (namely,
  ``agent_ilo``, ``agent_ipmitool``, ``agent_pyghmi``, ``agent_ssh`` or
  ``agent_vbox``) you have to know MD5 checksum for your instance image. To
  compute it, you can use the following command::

   md5sum image.qcow2
   ed82def8730f394fb85aef8a208635f6  image.qcow2

  Apart from that, because of the way the agent deploy method works, image
  hrefs can use only HTTP(S) protocol.

* If you're using ``iscsi_ilo`` or ``agent_ilo`` driver, Object Storage service
  is required, as these drivers need to store floppy image that is used to pass
  parameters to deployment iso. For this method also only HTTP(S) hrefs are
  acceptable, as HP iLO servers cannot attach other types of hrefs as virtual
  media.

* Other drivers use PXE deploy method and there are no special requirements
  in this case.

Steps to start a deployment are pretty similar to those when using Compute:

#. To use the `ironic CLI <http://docs.openstack.org/developer/python-ironicclient/cli.html>`_,
   set up these environment variables. Since no authentication strategy is
   being used, the value can be any string for OS_AUTH_TOKEN. IRONIC_URL is
   the URL of the ironic-api process.
   For example::

    export OS_AUTH_TOKEN=fake-token
    export IRONIC_URL=http://localhost:6385/

#. Create a node in Bare Metal service. At minimum, you must specify the driver
   name (for example, "pxe_ipmitool"). You can also specify all the required
   driver parameters in one command. This will return the node UUID::

    ironic node-create -d pxe_ipmitool -i ipmi_address=ipmi.server.net \
    -i ipmi_username=user -i ipmi_password=pass \
    -i deploy_kernel=file:///images/deploy.vmlinuz \
    -i deploy_ramdisk=http://my.server.net/images/deploy.ramdisk

    +--------------+--------------------------------------------------------------------------+
    | Property     | Value                                                                    |
    +--------------+--------------------------------------------------------------------------+
    | uuid         | be94df40-b80a-4f63-b92b-e9368ee8d14c                                     |
    | driver_info  | {u'deploy_ramdisk': u'http://my.server.net/images/deploy.ramdisk',       |
    |              | u'deploy_kernel': u'file:///images/deploy.vmlinuz', u'ipmi_address':     |
    |              | u'ipmi.server.net', u'ipmi_username': u'user', u'ipmi_password':         |
    |              | u'******'}                                                               |
    | extra        | {}                                                                       |
    | driver       | pxe_ipmitool                                                             |
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

    ironic port-create -n $NODE_UUID -a $MAC_ADDRESS

#. As there is no Compute service flavor and instance image is not provided with
   nova boot command, you also need to specify some fields in ``instance_info``.
   For PXE deployment, they are ``image_source``, ``kernel``, ``ramdisk``,
   ``root_gb``::

    ironic node-update $NODE_UUID add instance_info/image_source=$IMG \
    instance_info/kernel=$KERNEL instance_info/ramdisk=$RAMDISK \
    instance_info/root_gb=10

   Here $IMG, $KERNEL, $RAMDISK can also be HTTP(S) or file hrefs. For agent
   drivers, you don't need to specify kernel and ramdisk, but MD5 checksum of
   instance image is required::

    ironic node-update $NODE_UUID add instance_info/image_checksum=$MD5HASH

#. Validate that all parameters are correct::

    ironic node-validate $NODE_UUID

    +------------+--------+----------------------------------------------------------------+
    | Interface  | Result | Reason                                                         |
    +------------+--------+----------------------------------------------------------------+
    | console    | False  | Missing 'ipmi_terminal_port' parameter in node's driver_info.  |
    | deploy     | True   |                                                                |
    | management | True   |                                                                |
    | power      | True   |                                                                |
    +------------+--------+----------------------------------------------------------------+

#. Now you can start the deployment, run::

    ironic node-set-provision-state $NODE_UUID active

   You can manage provisioning by issuing this command. Valid provision states
   are ``active``, ``rebuild`` and ``deleted``.

For iLO drivers, fields that should be provided are:

* ``ilo_deploy_iso`` under ``driver_info``;

* ``ilo_boot_iso``, ``image_source``, ``root_gb`` under ``instance_info``.

.. note::
   Before Liberty release Ironic was not able to track non-Glance images'
   content changes. Starting with Liberty, it is possible to do so using image
   modification date. For example, for HTTP image, if 'Last-Modified' header
   value from response to a HEAD request to
   "http://my.server.net/images/deploy.ramdisk" is greater than cached image
   modification time, Ironic will re-download the content. For "file://"
   images, the file system modification time is used.


Other references
----------------

* :ref:`local-boot-without-compute`

