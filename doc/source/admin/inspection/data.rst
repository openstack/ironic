Inspection data
===============

The in-band inspection processes collects a lot of information about the node.
This data consists of two parts:

* *Inventory* depends on the inspection interface used. See
  :ref:`inventory`.
* *Plugin data* is data populated by ramdisk-side and server-side plug-ins.
  See :ref:`plugin-data`.

After a successful inspection, you can get both parts as JSON with:

.. code-block:: console

   $ baremetal node inventory save <NODE>

Use ``jq`` to filter the parts you need, e.g. only the inventory itself:

.. code-block:: console

   $ # System vendor information from the inventory
   $ baremetal node inventory save <NODE> | jq .inventory.system_vendor
   {
     "product_name": "KVM (9.2.0)",
     "serial_number": "",
     "manufacturer": "Red Hat",
     "firmware": {
       "vendor": "EDK II",
       "version": "edk2-20221207gitfff6d81270b5-7.el9",
       "build_date": "12/07/2022"
     }
   }

   $ # Interfaces used to create ports
   $ baremetal node inventory save <NODE> | jq .plugin_data.valid_interfaces
   {
     "eth0": {
       "name": "eth0",
       "mac_address": "52:54:00:5e:09:ff",
       "ipv4_address": "192.168.122.164",
       "ipv6_address": "fe80::5054:ff:fe5e:9ff",
       "has_carrier": true,
       "lldp": null,
       "vendor": "0x1af4",
       "product": "0x0001",
       "client_id": null,
       "biosdevname": null,
       "speed_mbps": null,
       "pxe_enabled": true
     }
   }

.. _inventory:

Inventory
---------

The shape of the ``inventory`` depends on the inspection interface used.

* *agent* - For information on what gets reported by this interface see
  :ironic-python-agent-doc:`hardware inventory
  <admin/how_it_works.html#hardware-inventory>`.
* *redfish* - This interface aspires to the *agent* implementation but
  is known to be incomplete at this time.

Since many server-side plug-ins, known as
:doc:`hooks` live in the Ironic source tree
an effort is being made to define it here.

Top-Level
~~~~~~~~~

.. csv-table::
    :header: "Key", "Details"

    "``cpu``", "JSON object of CPU details"
    "``memory``", "JSON object of memory details"
    "``bmc_address``", "Optional IPv4 address as a string"
    "``bmc_v6address``", "Optional IPv6 address as a string"
    "``disk``", "List of JSON objects of disk details"
    "``interfaces``", "List of JSON objects of NIC details"
    "``system_vendor``", "JSON object of SMBIOS details"
    "``boot``", "JSON object of boot details"
    "``lldp_raw``", "Optional JSON object of LLDP data"
    "``pci_devices``", "Optional list of JSON objects of PCI details"
    "``usb_devices``", "Optional list of JSON objects of USB details"

.. _plugin-data:

Plugin data
-----------

Plugin data is the storage for all information that is collected or processed
by various plugins. Its format is not a part of the API stability promise
and may change depending on your configuration.

Plugin data comes from two sources:

* :ironic-python-agent-doc:`inspection collectors
  <admin/how_it_works.html#inspection-data>` - ramdisk-side inspection
  plug-ins.
* :doc:`hooks` - server-side inspection plug-ins.

.. TODO(dtantsur): inspection rules API once it's ready

Data storage
------------

There are several options to store the inspection data, specified via the
:oslo.config:option:`inventory.data_backend` option:

``none``
    Do not store inspection data at all. The API will always return 404 NOT
    FOUND.

``database``
    Store inspection data in a separate table in the main database.

``swift``
    Store inspection data in the Object Store service (swift) in the container
    specified by the :oslo.config:option:`inventory.swift_data_container`
    option.

.. warning::
   There is currently no way to migrate data between backends. Changing the
   backend will remove access to existing data.
