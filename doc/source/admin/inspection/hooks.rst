Inspection hooks
================

*Inspection hooks* are a type of the Bare Metal service plug-ins responsible
for processing data from in-band inspection. By configuring these hooks, an
operator can fully customize the inspection processing phase. How the data is
collected can be configured with `inspection collectors
<https://docs.openstack.org/ironic-python-agent/latest/admin/how_it_works.html#inspection-data>`_.

Configuring hooks
-----------------

Two configuration options are responsible for inspection hooks:
:oslo.config:option:`inspector.default_hooks` defines which hooks run by
default, while :oslo.config:option:`inspector.hooks` defines which hooks to run
in your deployment.  Only the second option should be modified by operators,
while the first one is to provide the defaults without hardcoding them:

.. code-block:: ini

   [inspector]
   hooks = $default_hooks

To make a hook run after the default ones, append it to the list, e.g.

.. code-block:: ini

   [inspector]
   hooks = $default_hooks,extra-hardware

Default hooks
-------------

In the order they go in the :oslo.config:option:`inspector.default_hooks`
option:

``ramdisk-error``
    Processes the ``error`` field from the ramdisk, aborting inspection if
    it is not empty.

``validate-interfaces``
    Validates network interfaces and stores the result in the ``plugin_data``
    in two fields:

    * ``all_interfaces`` - all interfaces that pass the basic sanity check.
    * ``valid_interfaces`` - interfaces that satisfy the configuration
      in the :oslo.config:option:`inspector.add_ports` option.

    In both cases, interfaces get an addition field:

    * ``pxe_enabled`` - whether PXE was enabled on this interface during
      the inspection boot.

``ports``
    Creates ports for interfaces in ``valid_interfaces`` as set by the
    ``validate-interfaces`` hook.

    Deletes ports that don't match the
    :oslo.config:option:`inspector.keep_ports` setting.

``architecture``
    Populates the ``cpu_arch`` property on the node.

Optional hooks
--------------

``accelerators``
    Populates the ``accelerators`` property based on the reported PCI devices.
    The known accelerators are specified in the YAML file linked in the
    :oslo.config:option:`inspector.known_accelerators` option. The default
    file is the following:

    .. literalinclude:: ../../../../ironic/drivers/modules/inspector/hooks/known_accelerators.yaml
       :language: YAML

``boot-mode``
    Sets the ``boot_mode`` capability based on the observed boot mode, see
    :ref:`boot_mode_support`.

``cpu-capabilities``
    Uses the CPU flags to :ref:`discover CPU capabilities
    <capabilities-discovery>`. The exact mapping can be customized via
    configuration:

    .. code-block:: ini

        [inspector]
        cpu_capabilities = vmx:cpu_vt,svm:cpu_vt

    See :oslo.config:option:`inspector.cpu_capabilities` for the default
    mapping.

``extra-hardware``
    Converts the data collected by python-hardware_ from its raw format
    into nested dictionaries under the ``extra`` plugin data field.

``local-link-connection``
    Uses the LLDP information from the ramdisk to populate the
    ``local_link_connection`` field on ports with the physical switch
    information.

``memory``
    Populates the ``memory_mb`` property based on physical RAM information
    from DMI.

``parse-lldp``
    Parses the raw binary LLDP information from the ramdisk and populates
    the ``parsed_lldp`` dictionary in plugin data. The keys are network
    interface names, the values are dictionaries with LLDP values. Example:

    .. code-block:: json

        "parsed_lldp": {
            "eth0": {
                "switch_chassis_id": "11:22:33:aa:bb:cc",
                "switch_system_name": "sw01-dist-1b-b12"
            }
        }

``pci-devices``
    Populates the capabilities based on PCI devices. The mapping is provided
    by the :oslo.config:option:`inspector.pci_device_alias` option.

``physical-network``
    Populates the ``physical_network`` port field for
    :doc:`/admin/multitenancy` based on the detected IP addresses. The mapping
    is provided by the
    :oslo.config:option:`inspector.physical_network_cidr_map` option.

``raid-device``
    Detects the newly created RAID device and populates the ``root_device``
    property used in :ref:`root device hints <root-device-hints>`. Requires two
    inspections: one before and one after the RAID creation.

``root-device``
    Uses :ref:`root device hints <root-device-hints>` on the node and the
    storage device information from the ramdisk to calculate the expected root
    device and populate the ``local_gb`` property (taking the
    :oslo.config:option:`inspector.disk_partitioning_spacing` option into
    account).

.. _python-hardware: https://github.com/redhat-cip/hardware
