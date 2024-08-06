==============
Redfish driver
==============

Overview
========

The ``redfish`` driver enables managing servers compliant with the
Redfish_ protocol. Supported features include:

* Network, :ref:`virtual media <redfish-virtual-media>` and :ref:`HTTP(s)
  <redfish-https-boot>` boot.
* Additional virtual media features:

  * :ref:`Ramdisk deploy interface <redfish-virtual-media-ramdisk>`.
  * :doc:`/admin/dhcp-less`.
  * `Virtual media API
    <https://docs.openstack.org/api-ref/baremetal/#attach-detach-virtual-media-nodes>`_.

* :ref:`Changing boot mode and secure boot status <redfish-boot-mode>`.
* :doc:`In-band </admin/inspection/index>` and `out-of-band inspection`_.
* Retrieving and changing :ref:`BIOS settings <redfish-bios-settings>`.
* Applying :doc:`firmware updates </admin/firmware-updates>`.
* Configuring :doc:`hardware RAID </admin/raid>`.
* :doc:`Hardware metrics <redfish/metrics>` and integration with
  `ironic-prometheus-exporter
  <https://docs.openstack.org/ironic-prometheus-exporter/latest/>`_.
* Event notifications configured via :doc:`redfish/passthru`.

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
   and ``redfish-https`` to ``enabled_boot_interfaces`` in
   ``/etc/ironic/ironic.conf``.
   For example::

    [DEFAULT]
    ...
    enabled_hardware_types = ipmi,redfish
    enabled_boot_interfaces = ipxe,redfish-virtual-media,redfish-https
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

``redfish_address``
    The URL address to the Redfish controller. It must include the authority
    portion of the URL, and can optionally include the scheme. If the scheme is
    missing, https is assumed. For example: ``https://mgmt.vendor.com``. This
    is required.

``redfish_system_id``
    The canonical path to the ComputerSystem resource that the driver will
    interact with. It should include the root service, version and the unique
    resource path to the ComputerSystem. This property is only required if
    target BMC manages more than one ComputerSystem. Otherwise ironic will pick
    the only available ComputerSystem automatically. For example:
    ``/redfish/v1/Systems/1``.

``redfish_username``
    User account with admin/server-profile access privilege. Although not
    required, it is highly recommended.

``redfish_password``
    User account password. Although not required, it is highly recommended.

``redfish_verify_ca``
    If ``redfish_address`` has the ``https://`` scheme, the driver will use a
    secure (TLS_) connection when talking to the Redfish controller. By default
    (if this is not set or set to ``True``), the driver will try to verify the
    host certificates. This can be set to the path of a certificate file or
    directory with trusted certificates that the driver will use for
    verification. To disable verifying TLS_, set this to ``False``. This is
    optional.

``redfish_auth_type``
    Redfish HTTP client authentication method. Can be ``basic``, ``session`` or
    ``auto``.  The ``auto`` mode first tries ``session`` and falls back to
    ``basic`` if session authentication is not supported by the Redfish BMC.
    Default is set in ironic config as :oslo.config:option:`redfish.auth_type`.
    Most operators should not need to leverage this setting. Session based
    authentication should generally be used in most cases as it prevents
    re-authentication every time a background task checks in with the BMC.

.. note::
   The ``redfish_address``, ``redfish_username``, ``redfish_password``,
   and ``redfish_verify_ca`` fields, if changed, will trigger a new session
   to be established and cached with the BMC. The ``redfish_auth_type`` field
   will only be used for the creation of a new cached session, or should
   one be rejected by the BMC.

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

.. _redfish-boot-mode:

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

Rebooting on boot mode changes
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

While some hardware is able to change the boot mode or the `UEFI secure boot`_
state immediately, other models may require a reboot for such a change to be
applied. Furthermore, some hardware models cannot change the boot mode and the
secure boot state simultaneously, requiring several reboots.

The Bare Metal service refreshes the System resource after issuing a PATCH
request against it. If the expected change is not observed, the node is
rebooted, and the Bare Metal service waits until the change is applied. In the
end, the previous power state is restored.

This logic makes changing boot configuration more robust at the expense of
several reboots in the worst case.

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
System Partition image (ESP_), see :doc:`/install/configure-esp` for details.

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
    --driver-info kernel_append_params="nofb vga=normal"

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
:doc:`/admin/dhcp-less` won't work. :doc:`/install/configure-esp` is also
unnecessary.

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

.. _redfish-https-boot:

Redfish HTTP(s) Boot
====================

The ``redfish-https`` boot interface is very similar to the
``redfish-virtual-media`` boot interface. In this driver, we compose an ISO
image, and request the BMC to inform the UEFI firmware to boot the Ironic
ramdisk, or a other ramdisk image. This approach is intended to allow a
pattern of engagement where we have minimal reliance on addressing and
discovery of the Ironic deployment through autoconfiguration like DHCP,
and somewhat mirrors vendor examples of booting from an HTTP URL.

This interface has some basic constraints.

* There is no configuration drive functionality, while Virtual Media did
  help provide such functionality.
* This interface *is* dependent upon BMC, EFI Firmware, and Bootloader,
  which means we may not see additional embedded files an contents in
  an ISO image. This is the same basic constraint over the ``ramdisk``
  deploy interface when using Network Booting.
* This is a UEFI-Only boot interface. No legacy boot is possible with
  this interface.

A good starting point for this interface, is to think of it as
higher security network boot, as we are explicitly telling the BMC
where the node should boot from.

Like the ``redfish-virtual-media`` boot interface, you will need
to create an EFI System Partition image (ESP_), see
:doc:`/install/configure-esp` for details on how to do this.

Additionally, if you would like to use the ``ramdisk`` deployment
interface, the same basic instructions covered in `Virtual Media Ramdisk`_
apply, just use ``redfish-https`` as the boot_interface, and keep in mind,
no configuration drives exist with the ``redfish-https`` boot interface.

Limitations & Issues
~~~~~~~~~~~~~~~~~~~~

Ironic contains two different ways of providing an HTTP(S) URL
to a remote BMC. The first is Swift, enabled when :oslo.config:option:`redfish.use_swift`
is set to ``true``. Ironic uploads files to Swift, which are then shared as
Temporary Swift URLs. While highly scalable, this method does suffer from
issues where some vendors BMCs reject URLs with **&** or **?** characters.
There is no available workaround to leverage Swift in this state.

When the :oslo.config:option:`redfish.use_swift` setting is set to ``false``, Ironic will house
the files locally in the :oslo.config:option:`deploy.http_root` folder structure, and then
generate a URL pointing the BMC to connect to the HTTP service configured
via :oslo.config:option:`deploy.http_url`.

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

.. _redfish-bios-settings:

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

Further topics
==============

.. toctree::

   redfish/metrics
   redfish/passthru
   redfish/session-cache
   redfish/interop

.. _Redfish: http://redfish.dmtf.org/
.. _Sushy: https://opendev.org/openstack/sushy
.. _TLS: https://en.wikipedia.org/wiki/Transport_Layer_Security
.. _ESP: https://wiki.ubuntu.com/EFIBootLoaders#Booting_from_EFI
.. _`BIOS Registry`: https://redfish.dmtf.org/schemas/v1/AttributeRegistry.v1_3_5.json
.. _`BIOS Configuration`: https://docs.openstack.org/ironic/latest/admin/bios.html
