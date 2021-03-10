Enrollment
==========

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
  checksum, you can use the following command:

  .. code-block:: console

   $ md5sum image.qcow2
   ed82def8730f394fb85aef8a208635f6  image.qcow2

  Alternatively, use a SHA256 checksum or any other algorithm supported by
  the Python's hashlib_, e.g.:

  .. code-block:: console

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

Enrolling nodes
---------------

#. Create a node in Bare Metal service. At minimum, you must specify the driver
   name (for example, ``ipmi``). You can also specify all the required
   driver parameters in one command. This will return the node UUID:

   .. code-block:: console

    $ baremetal node create --driver ipmi \
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
   address. In this case, they're used for naming of PXE configs for a node:

   .. code-block:: shell

    baremetal port create $MAC_ADDRESS --node $NODE_UUID
