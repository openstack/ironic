Firmware update using manual cleaning
=====================================

The firmware update cleaning step allows one or more firmware updates to be
applied to a node. If multiple updates are specified, then they are applied
sequentially in the order given. The server is rebooted once per update.
If a failure occurs, the cleaning step immediately fails which may result
in some updates not being applied. If the node is placed into maintenance
mode while a firmware update cleaning step is running that is performing
multiple firmware updates, the update in progress will complete, and processing
of the remaining updates will pause.  When the node is taken out of maintenance
mode, processing of the remaining updates will continue.

.. note:: Only :doc:`/admin/drivers/redfish` supports firmware updates
   currently.

When updating the BMC firmware, the BMC may become unavailable for a period of
time as it resets. In this case, it may be desirable to have the cleaning step
wait after the update has been applied before indicating that the
update was successful. This allows the BMC time to fully reset before further
operations are carried out against it. To cause the cleaning step to wait after
applying an update, an optional ``wait`` argument may be specified in the
firmware image dictionary. The value of this argument indicates the number of
seconds to wait following the update. If the ``wait`` argument is not
specified, then this is equivalent to ``wait 0``, meaning that it will not
wait and immediately proceed with the next firmware update if there is one,
or complete the cleaning step if not.

How it works
------------

The ``update_firmware`` cleaning step accepts JSON in the following format::

    [{
        "interface": "management",
        "step": "update_firmware",
        "args": {
            "firmware_images":[
                {
                    "url": "<url_to_firmware_image1>",
                    "checksum": "<checksum for image, uses SHA1, SHA256, or SHA512>",
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

``source`` corresponds to :oslo.config:option:`redfish.firmware_source` and by
setting it here, it is possible to override global setting per firmware image
in clean step arguments.

.. note::
   At the present time, targets for the firmware update cannot be specified.
   In testing, the BMC applied the update to all applicable targets on the
   node. It is assumed that the BMC knows what components a given firmware
   image is applicable to.

Applying updates
----------------

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
``source`` added, uses setting from :oslo.config:option:`redfish.firmware_source` to determine
if and where to stage the files:

.. code-block:: json

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
``firmware_update.json``:

.. code-block:: console

   $ baremetal node clean <ironic_node_uuid> --clean-steps firmware_update.json

In the following example, the JSON is specified directly on the command line:

.. code-block:: console

   $ baremetal node clean <ironic_node_uuid> --clean-steps \
       '[{"interface": "management", "step": "update_firmware", "args": {"firmware_images":[{"url": "http://192.0.2.10/BMC_4_22_00_00.EXE", "wait": 300}, {"url": "https://192.0.2.10/NIC_19.0.12_A00.EXE"}]}}]'

.. note::
   Firmware updates may take some time to complete. If a firmware update
   cleaning step consistently times out, then consider performing fewer
   firmware updates in the cleaning step or increasing
   ``clean_callback_timeout`` in ironic.conf to increase the timeout value.

.. warning::
   Warning: Removing power from a server while it is in the process of updating
   firmware may result in devices in the server, or the server itself becoming
   inoperable.
