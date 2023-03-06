=================
Deploy Interfaces
=================

A *deploy* interface plays a critical role in the provisioning process. It
orchestrates the whole deployment and defines how the image gets transferred
to the target disk.

.. _direct-deploy:

Direct deploy
=============

With ``direct`` deploy interface, the deploy ramdisk fetches the image from an
HTTP location. It can be an object storage (swift or RadosGW) temporary URL or
a user-provided HTTP URL. The deploy ramdisk then copies the image to the
target disk. See :ref:`direct deploy diagram <direct-deploy-example>` for
a detailed explanation of how this deploy interface works.

You can specify this deploy interface when creating or updating a node::

    baremetal node create --driver ipmi --deploy-interface direct
    baremetal node set <NODE> --deploy-interface direct

.. note::
    For historical reasons the ``direct`` deploy interface is sometimes called
    ``agent``. This is because before the Kilo release **ironic-python-agent**
    used to only support this deploy interface.

.. _image_download_source:

Deploy with custom HTTP servers
-------------------------------

The ``direct`` deploy interface can also be configured to use with custom HTTP
servers set up at ironic conductor nodes, images will be cached locally and
made accessible by the HTTP server.

To use this deploy interface with a custom HTTP server, set
``image_download_source`` to ``http`` in the ``[agent]`` section.

.. code-block:: ini

   [agent]
   ...
   image_download_source = http
   ...

This configuration affects *glance* and ``file://`` images. If you want
``http(s)://`` images to also be cached and served locally, use instead:

.. code-block:: ini

   [agent]
   image_download_source = local

.. note::
   This option can also be set per node in ``driver_info``::

    baremetal node set <node> --driver-info image_download_source=local

   or per instance in ``instance_info``::

    baremetal node set <node> --instance-info image_download_source=local

You need to set up a workable HTTP server at each conductor node which with
``direct`` deploy interface enabled, and check http related options in the
ironic configuration file to match the HTTP server configurations.

.. code-block:: ini

   [deploy]
   http_url = http://example.com
   http_root = /httpboot

.. note::
   See also: :ref:`l3-external-ip`.

Each HTTP server should be configured to follow symlinks for images
accessible from HTTP service. Please refer to configuration option
``FollowSymLinks`` if you are using Apache HTTP server, or
``disable_symlinks`` if Nginx HTTP server is in use.

.. _stream_raw_images:

Streaming raw images
--------------------

The Bare Metal service is capable of streaming raw images directly to the
target disk of a node, without caching them in the node's RAM. When the source
image is not already raw, the conductor will convert the image and calculate
the new checksum.

.. note::
   If no algorithm is specified via the ``image_os_hash_algo`` field, or if
   this field is set to ``md5``, SHA256 is used for the updated checksum.

For HTTP or local file images that are already raw, you need to explicitly set
the disk format to prevent the checksum from being unnecessarily re-calculated.
For example:

.. code-block:: shell

    baremetal node set <node> \
        --instance-info image_source=http://server/myimage.img \
        --instance-info image_os_hash_algo=sha512 \
        --instance-info image_os_hash_value=<SHA512 of the raw image> \
        --instance-info image_disk_format=raw

To disable this feature and cache images in the node's RAM, set

.. code-block:: ini

   [agent]
   stream_raw_images = False

To disable the conductor-side conversion completely, set

.. code-block:: ini

   [DEFAULT]
   force_raw_images = False

.. _ansible-deploy:

Ansible deploy
==============

This interface is similar to ``direct`` in the sense that the image
is downloaded by the ramdisk directly from the image store
(not from ironic-conductor host), but the logic of provisioning the node
is held in a set of Ansible playbooks that are applied by the
``ironic-conductor`` service handling the node.
While somewhat more complex to set up, this deploy interface provides greater
flexibility in terms of advanced node preparation during provisioning.

This interface is supported by most but not all hardware types declared
in ironic.
However this deploy interface is not enabled by default.
To enable it, add ``ansible`` to the list of enabled deploy
interfaces in ``enabled_deploy_interfaces`` option in the ``[DEFAULT]``
section of ironic's configuration file:

.. code-block:: ini

   [DEFAULT]
   ...
   enabled_deploy_interfaces = direct,ansible
   ...

Once enabled, you can specify this deploy interface when creating or updating
a node:

.. code-block:: shell

   baremetal node create --driver ipmi --deploy-interface ansible
   baremetal node set <NODE> --deploy-interface ansible

For more information about this deploy interface, its features and how to use
it, see :doc:`Ansible deploy interface <../drivers/ansible>`.


.. toctree::
   :hidden:

   ../drivers/ansible

Anaconda deploy
===============

The ``anaconda`` deploy interface is another option for highly customized
deployments.  See :doc:`/admin/anaconda-deploy-interface` for more details.

Ramdisk deploy
==============

The ramdisk interface is intended to provide a mechanism to "deploy" an
instance where the item to be deployed is in reality a ramdisk. It is
documented separately, see :doc:`/admin/ramdisk-boot`.

.. _custom-agent-deploy:

Custom agent deploy
===================

The ``custom-agent`` deploy interface is designed for operators who want to
completely orchestrate writing the instance image using
:ironic-python-agent-doc:`in-band deploy steps from a custom agent image
<admin/hardware_managers.html>`. If you use this deploy interface, you are
responsible to provide all necessary deploy steps with priorities between
61 and 99 (see :ref:`node-deployment-core-steps` for information on
priorities).
