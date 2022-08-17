==============
Redfish driver
==============

Overview
========

The ``redfish`` driver enables managing servers compliant with the
Redfish_ protocol.

Prerequisites
=============

* The Sushy_ library should be installed on the ironic conductor node(s).

  For example, it can be installed with ``pip``::

      sudo pip install sushy

Enabling the Redfish driver
===========================

#. Add ``redfish`` to the list of ``enabled_hardware_types``,
   ``enabled_power_interfaces``, ``enabled_management_interfaces`` and
   ``enabled_inspect_interfaces`` as well as ``redfish-virtual-media``
   to ``enabled_boot_interfaces`` in ``/etc/ironic/ironic.conf``.
   For example::

    [DEFAULT]
    ...
    enabled_hardware_types = ipmi,redfish
    enabled_boot_interfaces = ipxe,redfish-virtual-media
    enabled_power_interfaces = ipmitool,redfish
    enabled_management_interfaces = ipmitool,redfish
    enabled_inspect_interfaces = inspector,redfish

#. Restart the ironic conductor service::

    sudo service ironic-conductor restart

    # Or, for RDO:
    sudo systemctl restart openstack-ironic-conductor

Registering a node with the Redfish driver
===========================================

Nodes configured to use the driver should have the ``driver`` property
set to ``redfish``.

The following properties are specified in the node's ``driver_info``
field:

- ``redfish_address``: The URL address to the Redfish controller. It must
                       include the authority portion of the URL, and can
                       optionally include the scheme. If the scheme is
                       missing, https is assumed.
                       For example: https://mgmt.vendor.com. This is required.

- ``redfish_system_id``: The canonical path to the ComputerSystem resource
                         that the driver will interact with. It should include
                         the root service, version and the unique resource
                         path to the ComputerSystem. This property is only
                         required if target BMC manages more than one
                         ComputerSystem. Otherwise ironic will pick the only
                         available ComputerSystem automatically. For
                         example: /redfish/v1/Systems/1.

- ``redfish_username``: User account with admin/server-profile access
                        privilege. Although not required, it is highly
                        recommended.

- ``redfish_password``: User account password. Although not required, it is
                        highly recommended.

- ``redfish_verify_ca``: If redfish_address has the **https** scheme, the
                         driver will use a secure (TLS_) connection when
                         talking to the Redfish controller. By default
                         (if this is not set or set to True), the driver
                         will try to verify the host certificates. This
                         can be set to the path of a certificate file or
                         directory with trusted certificates that the
                         driver will use for verification. To disable
                         verifying TLS_, set this to False. This is optional.

- ``redfish_auth_type``: Redfish HTTP client authentication method. Can be
                         "basic", "session" or "auto".
                         The "auto" mode first tries "session" and falls back
                         to "basic" if session authentication is not supported
                         by the Redfish BMC. Default is set in ironic config
                         as ``[redfish]auth_type``.


The ``baremetal node create`` command can be used to enroll
a node with the ``redfish`` driver. For example:

.. code-block:: bash

  baremetal node create --driver redfish --driver-info \
    redfish_address=https://example.com --driver-info \
    redfish_system_id=/redfish/v1/Systems/CX34R87 --driver-info \
    redfish_username=admin --driver-info redfish_password=password \
    --name node-0

For more information about enrolling nodes see :ref:`enrollment`
in the install guide.

Boot mode support
=================

The ``redfish`` hardware type can read current boot mode from the
bare metal node as well as set it to either Legacy BIOS or UEFI.

.. note::

   Boot mode management is the optional part of the Redfish specification.
   Not all Redfish-compliant BMCs might implement it. In that case
   it remains the responsibility of the operator to configure proper
   boot mode to their bare metal nodes.

UEFI secure boot
~~~~~~~~~~~~~~~~

Secure boot mode can be automatically set and unset during deployment for nodes
in UEFI boot mode, see :ref:`secure-boot` for an explanation how to use it.

Two clean and deploy steps are provided for key management:

``management.reset_secure_boot_keys_to_default``
    resets secure boot keys to their manufacturing defaults.
``management.clear_secure_boot_keys``
    removes all secure boot keys from the node.

Out-Of-Band inspection
======================

The ``redfish`` hardware type can inspect the bare metal node by querying
Redfish compatible BMC. This process is quick and reliable compared to the
way the ``inspector`` hardware type works i.e. booting bare metal node
into the introspection ramdisk.

.. note::

   The ``redfish`` inspect interface relies on the optional parts of the
   Redfish specification. Not all Redfish-compliant BMCs might serve the
   required information, in which case bare metal node inspection will fail.

.. note::

   The ``local_gb`` property cannot always be discovered, for example, when a
   node does not have local storage or the Redfish implementation does not
   support the required schema. In this case the property will be set to 0.

.. _redfish-virtual-media:

Virtual media boot
==================

The idea behind virtual media boot is that BMC gets hold of the boot image
one way or the other (e.g. by HTTP GET, other methods are defined in the
standard), then "inserts" it into node's virtual drive as if it was burnt
on a physical CD/DVD. The node can then boot from that virtual drive into
the operating system residing on the image.

The major advantage of virtual media boot feature is that potentially
unreliable TFTP image transfer phase of PXE protocol suite is fully
eliminated.

Hardware types based on the ``redfish`` fully support booting deploy/rescue
and user images over virtual media. Ironic builds bootable ISO images, for
either UEFI or BIOS (Legacy) boot modes, at the moment of node deployment out
of kernel and ramdisk images associated with the ironic node.

To boot a node managed by ``redfish`` hardware type over virtual media using
BIOS boot mode, it suffice to set ironic boot interface to
``redfish-virtual-media``, as opposed to ``ipmitool``.

.. code-block:: bash

  baremetal node set --boot-interface redfish-virtual-media node-0

.. note::
   iDRAC firmware before 4.40.10.00 (on Intel systems) and 6.00.00.00
   (on AMD systems) requires a non-standard Redfish call to boot from virtual
   media. Consider upgrading to 6.00.00.00, otherwise you **must** use
   the ``idrac`` hardware type and the ``idrac-redfish-virtual-media`` boot
   interface with older iDRAC firmware instead. For simplicity Ironic restricts
   both AMD and Intel systems before firmware version 6.00.00.00. See
   :doc:`/admin/drivers/idrac` for more details on this hardware type.

If UEFI boot mode is desired, the user should additionally supply EFI
System Partition image (ESP_), see `Configuring an ESP image`_ for details.

If ``[driver_info]/config_via_floppy`` boolean property of the node is set to
``true``, ironic will create a file with runtime configuration parameters,
place into on a FAT image, then insert the image into node's virtual floppy
drive.

When booting over PXE or virtual media, and user instance requires some
specific kernel configuration, the node's
``instance_info[kernel_append_params]`` or
``driver_info[kernel_append_params]`` properties can be used to pass
user-specified kernel command line parameters.

.. code-block:: bash

  baremetal node set node-0 \
    --driver-info kernel_append_params="nofb nomodeset vga=normal"

.. note::
   The ``driver_info`` field is supported starting with the Xena release.

Starting with the Zed cycle, you can combine the parameters from the
configuration and from the node using the special ``%default%`` syntax:

.. code-block:: bash

  baremetal node set node-0 \
    --driver-info kernel_append_params="%default% console=ttyS0,115200n8"

For ramdisk boot, the ``instance_info[ramdisk_kernel_arguments]`` property
serves the same purpose (``%default%`` is not supported since there is no
default value in the configuration).

Pre-built ISO images
~~~~~~~~~~~~~~~~~~~~

By default an ISO images is built per node using the deploy kernel and
initramfs provided in the configuration or the node's ``driver_info``. Starting
with the Wallaby release it's possible to provide a pre-built ISO image:

.. code-block:: bash

  baremetal node set node-0 \
    --driver_info deploy_iso=http://url/of/deploy.iso \
    --driver_info rescue_iso=http://url/of/rescue.iso

.. note::
   OpenStack Image service (glance) image IDs and ``file://`` links are also
   accepted.

.. note::
   Before the Xena release the parameters were called ``redfish_deploy_iso``
   and ``redfish_rescue_iso`` accordingly. The old names are still supported
   for backward compatibility.

No customization is currently done to the image, so e.g.
:doc:`/admin/dhcp-less` won't work. `Configuring an ESP image`_ is also
unnecessary.

Configuring an ESP image
~~~~~~~~~~~~~~~~~~~~~~~~~

An ESP image is an image that contains the necessary bootloader to boot the ISO
in UEFI mode. You will need a GRUB2 image file, as well as Shim for secure
boot. See :ref:`uefi-pxe-grub` for an explanation how to get them.

Then the following script can be used to build an ESP image:

.. code-block:: bash

   DEST=/path/to/esp.img
   GRUB2=/path/to/grub.efi
   SHIM=/path/to/shim.efi
   TEMP_MOUNT=$(mktemp -d)

   dd if=/dev/zero of=$DEST bs=4096 count=1024
   mkfs.fat -s 4 -r 512 -S 4096 $DEST

   sudo mount $DEST $TEMP_MOUNT
   sudo mkdir -p $DEST/EFI/BOOT
   sudo cp "$SHIM" $DEST/EFI/BOOT/BOOTX64.efi
   sudo cp "$GRUB2" $DEST/EFI/BOOT/GRUBX64.efi
   sudo umount $TEMP_MOUNT

.. note::
   If you use an architecture other than x86-64, you'll need to adjust the
   destination paths.

The resulting image should be provided via the ``driver_info/bootloader``
ironic node property in form of an image UUID or a URL:

.. code-block:: bash

   baremetal node set --driver-info bootloader=<glance-uuid-or-url> node-0

Alternatively, set the bootloader UUID or URL in the configuration file:

.. code-block:: ini

   [conductor]
   bootloader = <glance-uuid-or-url>

Finally, you need to provide the correct GRUB2 configuration path for your
image. In most cases this path will depend on your distribution, more
precisely, the distribution you took the GRUB2 image from. For example:

CentOS:

.. code-block:: ini

   [DEFAULT]
   grub_config_path = EFI/centos/grub.cfg

Ubuntu:

.. code-block:: ini

   [DEFAULT]
   grub_config_path = EFI/ubuntu/grub.cfg

.. note::
   Unlike in the script above, these paths are case-sensitive!

.. _redfish-virtual-media-ramdisk:

Virtual Media Ramdisk
~~~~~~~~~~~~~~~~~~~~~

The ``ramdisk`` deploy interface can be used in concert with the
``redfish-virtual-media`` boot interface to facilitate the boot of a remote
node utilizing pre-supplied virtual media. See :doc:`/admin/ramdisk-boot` for
information on how to enable and configure it.

Instead of supplying an ``[instance_info]/image_source`` parameter, a
``[instance_info]/boot_iso`` parameter can be supplied. The image will
be downloaded by the conductor, and the instance will be booted using
the supplied ISO image. In accordance with the ``ramdisk`` deployment
interface behavior, once booted the machine will have a ``provision_state``
of ``ACTIVE``.

.. code-block:: bash

  baremetal node set <node name or UUID> \
      --boot-interface redfish-virtual-media \
      --deploy-interface ramdisk \
      --instance_info boot_iso=http://url/to.iso

This initial interface does not support bootloader configuration
parameter injection, as such the ``[instance_info]/kernel_append_params``
setting is ignored.

Configuration drives are supported starting with the Wallaby release
for nodes that have a free virtual USB slot:

.. code-block:: bash

  baremetal node deploy <node name or UUID> \
      --config-drive '{"meta_data": {...}, "user_data": "..."}'

or via a link to a raw image:

.. code-block:: bash

  baremetal node deploy <node name or UUID> \
      --config-drive http://example.com/config.img

Layer 3 or DHCP-less ramdisk booting
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

DHCP-less deploy is supported by the Redfish virtual media boot. See
:doc:`/admin/dhcp-less` for more information.

Firmware update using manual cleaning
=====================================

The ``redfish`` hardware type supports updating the firmware on nodes using a
manual cleaning step.

The firmware update cleaning step allows one or more firmware updates to be
applied to a node. If multiple updates are specified, then they are applied
sequentially in the order given. The server is rebooted once per update.
If a failure occurs, the cleaning step immediately fails which may result
in some updates not being applied. If the node is placed into maintenance
mode while a firmware update cleaning step is running that is performing
multiple firmware updates, the update in progress will complete, and processing
of the remaining updates will pause.  When the node is taken out of maintenance
mode, processing of the remaining updates will continue.

When updating the BMC firmware, the BMC may become unavailable for a period of
time as it resets. In this case, it may be desireable to have the cleaning step
wait after the update has been applied before indicating that the
update was successful. This allows the BMC time to fully reset before further
operations are carried out against it. To cause the cleaning step to wait after
applying an update, an optional ``wait`` argument may be specified in the
firmware image dictionary. The value of this argument indicates the number of
seconds to wait following the update. If the ``wait`` argument is not
specified, then this is equivalent to ``wait 0``, meaning that it will not
wait and immediately proceed with the next firmware update if there is one,
or complete the cleaning step if not.

The ``update_firmware`` cleaning step accepts JSON in the following format::

    [{
        "interface": "management",
        "step": "update_firmware",
        "args": {
            "firmware_images":[
                {
                    "url": "<url_to_firmware_image1>",
                    "checksum": "<checksum for image, uses SHA1>",
                    "source": "<optional override source setting for image>",
                    "wait": <number_of_seconds_to_wait>
                },
                {
                    "url": "<url_to_firmware_image2>"
                },
                ...
            ]
        }
    }]

The different attributes of the ``update_firmware`` cleaning step are as follows:

.. csv-table::
    :header: "Attribute", "Description"
    :widths: 30, 120

    "``interface``", "Interface of the cleaning step.  Must be ``management`` for firmware update"
    "``step``", "Name of cleaning step.  Must be ``update_firmware`` for firmware update"
    "``args``", "Keyword-argument entry (<name>: <value>) being passed to cleaning step"
    "``args.firmware_images``", "Ordered list of dictionaries of firmware images to be applied"

Each firmware image dictionary, is of the form::

    {
      "url": "<URL of firmware image file>",
      "checksum": "<checksum for image, uses SHA1>",
      "source": "<Optional override source setting for image>",
      "wait": <Optional time in seconds to wait after applying update>
    }

The ``url`` and ``checksum`` arguments in the firmware image dictionary are
mandatory, while the ``source`` and ``wait`` arguments are optional.

For ``url`` currently ``http``, ``https``, ``swift`` and ``file`` schemes are
supported.

``source`` corresponds to ``[redfish]firmware_source`` and by setting it here,
it is possible to override global setting per firmware image in clean step
arguments.


.. note::
   At the present time, targets for the firmware update cannot be specified.
   In testing, the BMC applied the update to all applicable targets on the
   node. It is assumed that the BMC knows what components a given firmware
   image is applicable to.

To perform a firmware update, first download the firmware to a web server,
Swift or filesystem that the Ironic conductor or BMC has network access to.
This could be the ironic conductor web server or another web server on the BMC
network. Using a web browser, curl, or similar tool on a server that has
network access to the BMC or Ironic conductor, try downloading the firmware to
verify that the URLs are correct and that the web server is configured
properly.

Next, construct the JSON for the firmware update cleaning step to be executed.
When launching the firmware update, the JSON may be specified on the command
line directly or in a file. The following example shows one cleaning step that
installs four firmware updates. All except 3rd entry that has explicit
``source`` added, uses setting from ``[redfish]firmware_source`` to determine
if and where to stage the files::

    [{
        "interface": "management",
        "step": "update_firmware",
        "args": {
            "firmware_images":[
                {
                    "url": "http://192.0.2.10/BMC_4_22_00_00.EXE",
                    "checksum": "<sha1-checksum-of-the-file>",
                    "wait": 300
                },
                {
                    "url": "https://192.0.2.10/NIC_19.0.12_A00.EXE",
                    "checksum": "<sha1-checksum-of-the-file>"
                },
                {
                    "url": "file:///firmware_images/idrac/9/PERC_WN64_6.65.65.65_A00.EXE",
                    "checksum": "<sha1-checksum-of-the-file>",
                    "source": "http"
                },
                {
                    "url": "swift://firmware_container/BIOS_W8Y0W_WN64_2.1.7.EXE",
                    "checksum": "<sha1-checksum-of-the-file>"
                }
            ]
        }
    }]

Finally, launch the firmware update cleaning step against the node. The
following example assumes the above JSON is in a file named
``firmware_update.json``::

    baremetal node clean <ironic_node_uuid> --clean-steps firmware_update.json

In the following example, the JSON is specified directly on the command line::

    baremetal node clean <ironic_node_uuid> --clean-steps '[{"interface": "management", "step": "update_firmware", "args": {"firmware_images":[{"url": "http://192.0.2.10/BMC_4_22_00_00.EXE", "wait": 300}, {"url": "https://192.0.2.10/NIC_19.0.12_A00.EXE"}]}}]'

.. note::
   Firmware updates may take some time to complete. If a firmware update
   cleaning step consistently times out, then consider performing fewer
   firmware updates in the cleaning step or increasing
   ``clean_callback_timeout`` in ironic.conf to increase the timeout value.

.. warning::
   Warning: Removing power from a server while it is in the process of updating
   firmware may result in devices in the server, or the server itself becoming
   inoperable.

Retrieving BIOS Settings
========================

When the :doc:`bios interface </admin/bios>` is set to ``redfish``, Ironic will
retrieve the node's BIOS settings as described in `BIOS Configuration`_. In
addition, via Sushy_, Ironic will get the BIOS Attribute Registry
(`BIOS Registry`_) from the node which is a schema providing details on the
settings. The following fields will be returned in the BIOS API
(``/v1/nodes/{node_ident}/bios``) along with the setting name and value:

.. csv-table::
    :header: "Field", "Description"
    :widths: 25, 120

    "``attribute_type``", "The type of setting - ``Enumeration``, ``Integer``, ``String``, ``Boolean``, or ``Password``"
    "``allowable_values``", "A list of allowable values when the attribute_type is ``Enumeration``"
    "``lower_bound``", "The lowest allowed value when attribute_type is ``Integer``"
    "``upper_bound``", "The highest allowed value when attribute_type is ``Integer``"
    "``min_length``", "The shortest string length that the value can have when attribute_type is ``String``"
    "``max_length``", "The longest string length that the value can have when attribute_type is ``String``"
    "``read_only``", "The setting is ready only and cannot be modified"
    "``unique``", "The setting is specific to this node"
    "``reset_required``", "After changing this setting a node reboot is required"

.. _node-vendor-passthru-methods:

Node Vendor Passthru Methods
============================

.. csv-table::
    :header: "Method", "Description"
    :widths: 25, 120

    "``create_subscription``", "Create a new subscription on the Node"
    "``delete_subscription``", "Delete a subscription of a Node"
    "``get_all_subscriptions``", "List all subscriptions of a Node"
    "``get_subscription``", "Show a single subscription of a Node"
    "``eject_vmedia``", "Eject attached virtual media from a Node"


Create Subscription
~~~~~~~~~~~~~~~~~~~

.. csv-table:: Request
    :header: "Name", "In", "Type", "Description"
    :widths: 25, 15, 15, 90

    "Destination", "body", "string", "The URI of the destination Event Service"
    "EventTypes (optional)", "body", "array",  "List of ypes of events that shall be sent to the destination"
    "Context (optional)", "body", "string", "A client-supplied string that is stored with the event destination
    subscription"
    "Protocol (optional)", "body", "string", "The protocol type that the event will use for sending
    the event to the destination"

Example JSON to use in ``create_subscription``::

    {
        "Destination": "https://someurl",
        "EventTypes": ["Alert"],
        "Context": "MyProtocol",
        "args": "Redfish"
    }


Delete Subscription
~~~~~~~~~~~~~~~~~~~

.. csv-table:: Request
    :header: "Name", "In", "Type", "Description"
    :widths: 21, 21, 21, 37

    "id", "body", "string", "The Id of the subscription generated by the BMC "


Example JSON to use in ``delete_subscription``::

    {
        "id": "<id of the subscription generated by the BMC>"
    }


Get Subscription
~~~~~~~~~~~~~~~~

.. csv-table:: Request
    :header: "Name", "In", "Type", "Description"
    :widths: 21, 21, 21, 37

    "id", "body", "string", "The Id of the subscription generated by the BMC "


Example JSON to use in ``get_subscription``::

    {
        "id": "<id of the subscription generated by the BMC>"
    }


Get All Subscriptions
~~~~~~~~~~~~~~~~~~~~~

The ``get_all_subscriptions`` doesn't require any parameters.


Eject Virtual Media
~~~~~~~~~~~~~~~~~~~

.. csv-table:: Request
    :header: "Name", "In", "Type", "Description"
    :widths: 25, 15, 15, 90

    "boot_device (optional)", "body", "string", "Type of the device to eject (all devices by default)"

.. _Redfish: http://redfish.dmtf.org/
.. _Sushy: https://opendev.org/openstack/sushy
.. _TLS: https://en.wikipedia.org/wiki/Transport_Layer_Security
.. _ESP: https://wiki.ubuntu.com/EFIBootLoaders#Booting_from_EFI
.. _`BIOS Registry`: https://redfish.dmtf.org/schemas/v1/AttributeRegistry.v1_3_5.json
.. _`BIOS Configuration`: https://docs.openstack.org/ironic/latest/admin/bios.html
