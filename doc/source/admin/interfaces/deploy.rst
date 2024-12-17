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

Bootc Agent Deploy
==================

The ``bootc`` deploy interface is designed to enable operators to deploy
containers directly from a container image registry without intermediate
conversion steps, such as creating custom disk images for modifications.
This deployment interface utilizes the
`bootc project <https://containers.github.io/bootc/>`_.

Ultimately this enables a streamlined flow, where a user of the deployment
interface *can* create updated containers rapidly and the deployment interface
will deploy that container image in a streamlined fashion without the need
to create intermediate disk images and post the disk images in a location
where they can be accessed for deployment.

Ultimately this interface enables a streamlined flow, and offers
limited flexibility in the model of deployment. As a result, this
interface consumes the entire target disk on the host being deployed
and offers no customization in terms of partitioning. This is largely
because the overall security model of a bootc deployment, which leverages
os-tree, is also fundamentally different than the model to leverage
partition separation.

.. NOTE::
   This interface should be considered experimental and may evolve
   to include additional features as the Ironic project maintainers
   receive additional feedback.

.. NOTE::
   This interface is dependent upon the existence of ``bootc`` within a
   container image along with sufficient memory on the baremetal
   node being deployed to enable a complete download and extraction of image
   contents within system memory. It is this memory constraint which is
   why this interface is not actively tested in upstream CI.
   The possible failure modes of this interface are mainly focused upon
   the ability of the ramdisk being able to download, launch, and
   run bootc to trigger the installation which also isolates most risk
   to the actual bootc process execution.

Features
--------

While this ``deploy_interface`` supports deploying configuration drives
like most other Ironic supplied deploy interfaces, some additional
parameters can be supplied via ``instance_info`` to enable
tuning of deploy-time behavior by the user which cannot be modified
post-deployment.

* ``bootc_authorized_keys`` - This option allows injection of a
  root user authorized keys file which is preserved inside of the deployed
  container on the host. This option is for actual key file content and can
  be one or more keys with a new line character.
* ``bootc_tpm2_luks`` - A boolean option, default False, enabling bootc
  to attempt to utilize auto-encryption of the deployed host filesystem
  upon which the container is deployed. This is not enabled by default
  due to a lack of software TPMs in Ironic CI. If operators would like
  this setting default changed, please discuss with Ironic developers.

Additionally, this interface also supports the passing of a pull secret
to enable download from the remote image registry, which is part of the
support for retrieval of artifacts from OCI Container registires.
This parameter is ``image_pull_secret``.

Caveats
-------

* This deployment interface was not designed to be compatible with the
  OpenStack Compute service. This is because OpenStack focuses on
  disk images from Glance as to what to deploy, where as this interface
  is modeled to utilize a container image registry.
* Performance wise, this deployment interface performs many smaller actions,
  which at some times need to performed in a specific sequence, such as
  when unpacking layers. As a result, when comparing similar size
  containers to disk images, this interface is slower than the ``direct``
  deploy interface.
* Container Images *must* have the bootc command present along with
  the applicable bootloader and artifacts required for whatever platform
  is being deployed.
* Because of how `bootc <https://containers.github.io/bootc/>`_ works,
  there is no concept of "image streaming" directly to disk. This is because
  the way this interface works, `podman <https://podman.io/>`_ is used to
  download all container image layer artifacts, along with extracting the
  layers. At which point ``bootc`` is executed and it begins to setup the
  disk for the host. As a result, most of the time a deploy is in progress
  will be observable as ``deploy wait`` while ``bootc`` executes.
* The memory requirements of the ramdisk, due to the way this interface
  works, requires the ability to download a container image, copy, and
  ultimatley extract all layers into the in-memory filesystem. Due to the way
  the kernel launches and allocates ramdisk memory for filesystem usage,
  a 600MB container image may require upwards of 10GB of RAM to be available
  on the overall host.
* This deployment interface explicitly signals to ``bootc`` that it should
  not execute it's internal post-deployment "fetch check" to ensure upgrades
  are working. This is because this action may require authentication
  to succeed, **and** thus require credentials in the container to
  work. Configuration of credentials for **day-2** operations
  such as the execution of ``bootc upgrade``, must be addressed
  post-deployment.
* If you intend SELinux to be enabled on the deployed host, it must also
  be enabled inside of the ironic-python-agent ramdisk. This is a design
  limitation of bootc outside of Ironic's control.

Limitations
-----------

* At present, this interface does not support use of caching proxies. This
  may be addressed in the future.
* This deployment interface directly downloads artifacts from the requested
  Container Registry. Caching the container artifacts on the
  ``ironic-conductor`` host is not available. If you need the contaitainer
  content localized to the conductor, consider utilizing your own container
  registry.
