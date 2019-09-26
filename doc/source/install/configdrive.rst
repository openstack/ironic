.. _configdrive:

Enabling the configuration drive (configdrive)
==============================================

The Bare Metal service supports exposing a configuration drive image to
the instances.

The configuration drive is used to store instance-specific metadata and is present to
the instance as a disk partition labeled ``config-2``. The configuration drive has
a maximum size of 64MB. One use case for using the configuration drive is to
expose a networking configuration when you do not use DHCP to assign IP
addresses to instances.

The configuration drive is usually used in conjunction with the Compute
service, but the Bare Metal service also offers a standalone way of using it.
The following sections will describe both methods.


When used with Compute service
------------------------------

To enable the configuration drive for a specific request, pass
``--config-drive true`` parameter to the :command:`nova boot` command, for example::

    nova boot --config-drive true --flavor baremetal --image test-image instance-1

It's also possible to enable the configuration drive automatically on
all instances by configuring the ``OpenStack Compute service`` to always
create a configuration drive by setting the following option in the
``/etc/nova/nova.conf`` file, for example::

    [DEFAULT]
    ...

    force_config_drive=True

In some cases, you may wish to pass a user customized script when deploying an instance.
To do this, pass ``--user-data /path/to/file`` to the :command:`nova boot` command.

When used standalone
--------------------

When used without the Compute service, the operator needs to create a configuration drive
and provide the file or HTTP URL to the Bare Metal service.

For the format of the configuration drive, Bare Metal service expects a
``gzipped`` and ``base64`` encoded ISO 9660 [#]_ file with a ``config-2``
label. The `openstack baremetal client
<https://docs.openstack.org/python-ironicclient/train/cli/osc_plugin_cli.html>`_
can generate a configuration drive in the `expected format`_. Just pass a
directory path containing the files that will be injected into it via the
``--config-drive`` parameter of the ``openstack baremetal node deploy``
command, for example::

    openstack baremetal node deploy $node_identifier --config-drive /dir/configdrive_files

Starting with the Stein release and `ironicclient` 2.7.0, you can request
building a configdrive on the server side by providing a JSON with keys
``meta_data``, ``user_data`` and ``network_data`` (all optional), e.g.:

.. code-block:: bash

    openstack baremetal node deploy $node_identifier \
        --config-drive '{"meta_data": {"hostname": "server1.cluster"}}'

Configuration drive storage in an object store
----------------------------------------------

Under normal circumstances, the configuration drive can be stored in the
Bare Metal service when the size is less than 64KB. Optionally, if the size
is larger than 64KB there is support to store it in a swift endpoint. Both
swift and radosgw use swift-style APIs.

The following option in ``/etc/ironic/ironic.conf`` enables swift as an object
store backend to store config drive. This uses the Identity service to
establish a session between the Bare Metal service and the
Object Storage service. ::

    [deploy]
    ...

    configdrive_use_object_store = True

Use the following options in ``/etc/ironic/ironic.conf`` to enable radosgw.
Credentials in the swift section are needed because radosgw will not use the
Identity service and relies on radosgw's username and password authentication
instead. ::

    [deploy]
    ...

    configdrive_use_object_store = True

    [swift]
    ...

    username = USERNAME
    password = PASSWORD
    auth_url = http://RADOSGW_IP:8000/auth/v1

If the :ref:`direct-deploy` is being used, edit ``/etc/glance/glance-api.conf``
to store the instance images in respective object store (radosgw or swift)
as well::

    [glance_store]
    ...

    swift_store_user = USERNAME
    swift_store_key = PASSWORD
    swift_store_auth_address = http://RADOSGW_OR_SWIFT_IP:PORT/auth/v1


Accessing the configuration drive data
--------------------------------------

When the configuration drive is enabled, the Bare Metal service will create a partition on the
instance disk and write the configuration drive image onto it. The
configuration drive must be mounted before use. This is performed
automatically by many tools, such as cloud-init and cloudbase-init. To mount
it manually on a Linux distribution that supports accessing devices by labels,
simply run the following::

    mkdir -p /mnt/config
    mount /dev/disk/by-label/config-2 /mnt/config


If the guest OS doesn't support accessing devices by labels, you can use
other tools such as ``blkid`` to identify which device corresponds to
the configuration drive and mount it, for example::

    CONFIG_DEV=$(blkid -t LABEL="config-2" -odevice)
    mkdir -p /mnt/config
    mount $CONFIG_DEV /mnt/config


.. [#] A configuration drive could also be a data block with a VFAT filesystem
       on it instead of ISO 9660. But it's unlikely that it would be needed
       since ISO 9660 is widely supported across operating systems.


Cloud-init integration
----------------------

The configuration drive can be
especially useful when used with `cloud-init
<http://cloudinit.readthedocs.io/en/latest/topics/datasources/configdrive.html>`_,
but in order to use it we should follow some rules:

* ``Cloud-init`` data should be organized in the `expected format`_.


* Since the Bare Metal service uses a disk partition as the configuration drive,
  it will only work with
  `cloud-init version >= 0.7.5 <https://github.com/cloud-init/cloud-init/blob/2d6e4219db73e80c135efd83753f9302f778f08d/ChangeLog>`_.


* ``Cloud-init`` has a collection of data source modules, so when
  building the image with `disk-image-builder`_ we have to define
  ``DIB_CLOUD_INIT_DATASOURCES`` environment variable and set the
  appropriate sources to enable the configuration drive, for example::

    DIB_CLOUD_INIT_DATASOURCES="ConfigDrive, OpenStack" disk-image-create -o fedora-cloud-image fedora baremetal

  For more information see `how to configure cloud-init data sources
  <https://docs.openstack.org/diskimage-builder/latest/elements/cloud-init-datasources/README.html>`_.

.. _`expected format`: https://docs.openstack.org/nova/latest/user/vendordata.html
.. _disk-image-builder: https://docs.openstack.org/diskimage-builder/latest/
