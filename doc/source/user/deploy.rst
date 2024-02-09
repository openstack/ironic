Deploying with Bare Metal service
=================================

This guide explains how to use Ironic to deploy nodes without any front-end
service, such as OpenStack Compute (nova) or Metal3_.

.. note::
   To simplify this task you can use the metalsmith_ tool which provides a
   convenient CLI for the most common cases.

.. _Metal3: http://metal3.io/
.. _metalsmith: https://docs.openstack.org/metalsmith/latest/

Allocations
-----------

Allocation is a way to find and reserve a node suitable for deployment. When an
allocation is created, the list of available nodes is searched for a node with
the given *resource class* and *traits*, similarly to how it is done in
:doc:`OpenStack Compute flavors </install/configure-nova-flavors>`. Only the
resource class is mandatory, for example:

.. code-block:: console

    $ baremetal allocation create --resource-class baremetal --wait
    +-----------------+--------------------------------------+
    | Field           | Value                                |
    +-----------------+--------------------------------------+
    | candidate_nodes | []                                   |
    | created_at      | 2019-04-03T12:18:26+00:00            |
    | extra           | {}                                   |
    | last_error      | None                                 |
    | name            | None                                 |
    | node_uuid       | 5d946337-b1d9-4b06-8eda-4fb77e994a0d |
    | resource_class  | baremetal                            |
    | state           | active                               |
    | traits          | []                                   |
    | updated_at      | 2019-04-03T12:18:26+00:00            |
    | uuid            | e84f5d60-84f1-4701-a635-10ff90e2f3b0 |
    +-----------------+--------------------------------------+

.. note::
   The allocation processing is fast but nonetheless asynchronous. Use the
   ``--wait`` argument to wait for the results.

If an allocation is successful, it sets the node's ``instance_uuid`` to the
allocation UUID. The node's UUID can be retrieved from the allocation's
``node_uuid`` field.

An allocation is automatically deleted when the associated node is
unprovisioned. If you don't provision the node, you're responsible for deleting
the allocation.

See the `allocation API reference
<https://docs.openstack.org/api-ref/baremetal/?expanded=create-allocation-detail#create-allocation>`_
for more information on how to use allocations.

Populating instance information
-------------------------------

The node's ``instance_info`` field is a JSON object that contains all
information required for deploying an instance on bare metal. It has to be
populated before deployment and is automatically cleared on tear down.

Image information
~~~~~~~~~~~~~~~~~

You need to specify image information in the node's ``instance_info``
(see :doc:`/user/creating-images`):

* ``image_source`` - URL of the whole disk or root partition image,
  mandatory. The following schemes are supported: ``http://``, ``https://``
  and ``file://``. Files have to be accessible by the conductor. If the scheme
  is missing, an Image Service (glance) image UUID is assumed.

* In case the image source requires HTTP(s) Basic Authentication ``RFC 7616``
  then the relevant authentication strategy has to be configured as
  ``http_basic`` and supplied with credentials  in the ironic global config
  file. Further information about the authentication strategy selection
  can be found in :doc:`/admin/user-image-basic-auth`.

* ``root_gb`` - size of the root partition, required for partition images.

  .. note::
     Older versions of the Bare Metal service used to require a positive
     integer for ``root_gb`` even for whole-disk images. You may want to set
     it for compatibility.

* ``image_checksum`` - MD5 checksum of the image specified by
  ``image_source``, only required for ``http://`` images when using
  :ref:`direct-deploy`.

  Other checksum algorithms are supported via the ``image_os_hash_algo`` and
  ``image_os_hash_value`` fields. They may be used instead of the
  ``image_checksum`` field.

  .. warning::
     If your operating system is running in FIPS 140-2 mode, MD5 will not be
     available, and you **must** use SHA256 or another modern algorithm.

  Starting with the Stein release of ironic-python-agent can also be a URL
  to a checksums file, e.g. one generated with:

  .. code-block:: console

     $ cd /path/to/http/root
     $ md5sum *.img > checksums

* ``kernel``, ``ramdisk`` - HTTP(s) or file URLs of the kernel and initramfs of
  the target OS. Must be added **only** for partition images and only if
  network boot is required.  Supports the same schemes as ``image_source``.

An example for a partition image with local boot:

.. code-block:: shell

 baremetal node set $NODE_UUID \
     --instance-info image_source=http://image.server/my-image.qcow2 \
     --instance-info image_checksum=1f9c0e1bad977a954ba40928c1e11f33 \
     --instance-info image_type=partition \
     --instance-info root_gb=10

With a SHA256 hash:

.. code-block:: shell

 baremetal node set $NODE_UUID \
     --instance-info image_source=http://image.server/my-image.qcow2 \
     --instance-info image_os_hash_algo=sha256 \
     --instance-info image_os_hash_value=a64dd95e0c48e61ed741ff026d8c89ca38a51f3799955097c5123b1705ef13d4 \
     --instance-info image_type=partition \
     --instance-info root_gb=10

If you use network boot (or Ironic before Yoga), two more fields must be set:

.. code-block:: shell

 baremetal node set $NODE_UUID \
     --instance-info image_source=http://image.server/my-image.qcow2 \
     --instance-info image_checksum=1f9c0e1bad977a954ba40928c1e11f33 \
     --instance-info image_type=partition \
     --instance-info kernel=http://image.server/my-image.kernel \
     --instance-info ramdisk=http://image.server/my-image.initramfs \
     --instance-info root_gb=10

With a whole disk image and a checksum URL:

.. code-block:: shell

 baremetal node set $NODE_UUID \
     --instance-info image_source=http://image.server/my-image.qcow2 \
     --instance-info image_checksum=http://image.server/my-image.qcow2.CHECKSUM

.. note::
   Certain hardware types and interfaces may require additional or different
   fields to be provided. See specific guides under :doc:`/admin/drivers`.

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

Attaching virtual interfaces
----------------------------

If using the OpenStack Networking service (neutron), you can attach its ports
to a node before deployment as VIFs:

.. code-block:: shell

   baremetal node vif attach $NODE_UUID $PORT_UUID

.. warning::
   These are **neutron** ports, not **ironic** ports!

VIFs are automatically detached on deprovisioning.

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

#. Starting with the Wallaby release you can also request custom deploy steps,
   see :ref:`standalone-deploy-steps` for details.

.. _deploy-configdrive:

Deploying with a config drive
-----------------------------

The configuration drive is a small image used to store instance-specific
metadata and is present to the instance as a disk partition labeled
``config-2``. See :doc:`/install/configdrive` for a detailed explanation.

A configuration drive can be provided either as a whole ISO 9660 image or as
JSON input for building an image. A first-boot service, such as cloud-init_,
must be running on the instance image for the configuration to be applied.

.. _cloud-init: https://cloudinit.readthedocs.io/en/latest/

Building a config drive on the client side
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

For the format of the configuration drive, Bare Metal service expects a
``gzipped`` and ``base64`` encoded ISO 9660 file with a ``config-2``
label. The :python-ironicclient-doc:`baremetal client
<cli/osc_plugin_cli.html>` can generate a configuration drive in the `expected
format`_. Pass a directory path containing the files that will be injected
into it via the ``--config-drive`` parameter of the ``baremetal node deploy``
command, for example:

.. code-block:: shell

    baremetal node deploy $NODE_UUID --config-drive /dir/configdrive_files

.. note::
   A configuration drive could also be a data block with a VFAT filesystem on
   it instead of ISO 9660. But it's unlikely that it would be needed since ISO
   9660 is widely supported across operating systems.

.. _expected format: https://docs.openstack.org/nova/latest/user/metadata.html#config-drives

Building a config drive on the conductor side
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Starting with the Stein release and `ironicclient` 2.7.0, you can request
building a configdrive on the server side by providing a JSON with keys
``meta_data``, ``user_data`` and ``network_data`` (all optional), e.g.:

.. code-block:: bash

    baremetal node deploy $node_identifier \
        --config-drive '{"meta_data": {"hostname": "server1.cluster"}}'

.. note::
   When this feature is used, host name defaults to the node's name or UUID.

SSH public keys can be provided as a mapping:

.. code-block:: shell

    baremetal node deploy $NODE_UUID \
        --config-drive '{"meta_data": {"public_keys": {"0": "ssh key contents"}}}'

If using cloud-init_, its configuration can be supplied as ``user_data``, e.g.:

.. code-block:: shell

    baremetal node deploy $NODE_UUID \
        --config-drive '{"user_data": "#cloud-config\n{\"users\": [{\"name\": ...}]}"}'

.. warning::
   User data is a string, not a JSON! Also note that a prefix, such as
   ``#cloud-config``, is required, see `user data format
   <https://cloudinit.readthedocs.io/en/latest/topics/format.html>`_.

Some first-boot services support network configuration in the `OpenStack
network data format
<https://docs.openstack.org/nova/latest/user/metadata.html#openstack-format-metadata>`_.
It can be provided in the ``network_data`` field of the configuration drive.

Ramdisk booting
---------------

Advanced operators, specifically ones working with ephemeral workloads,
may find it more useful to explicitly treat a node as one that would always
boot from a Ramdisk. See :doc:`/admin/ramdisk-boot` for details.
