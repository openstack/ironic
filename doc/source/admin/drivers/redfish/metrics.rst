Redfish hardware metrics
========================

The ``redfish`` hardware type supports sending hardware metrics via the
:doc:`notification system </admin/notifications>`. The ``event_type`` field of
a notification will be set to ``hardware.redfish.metrics`` (where ``redfish``
may be replaced by a different driver name for hardware types derived from it).

The payload of each notification is a mapping where keys are sensor types
(``Fan``, ``Temperature``, ``Power`` or ``Drive``) and values are also mappings
from sensor identifiers to the sensor data.

Each ``Fan`` payload contains the following fields:

* ``max_reading_range``, ``min_reading_range`` - the range of reading values.
* ``reading``, ``reading_units`` - the current reading and its units.
* ``serial_number`` - the serial number of the fan sensor.
* ``physical_context`` - the context of the sensor, such as ``SystemBoard``.
  Can also be ``null`` or just ``Fan``.

Each ``Temperature`` payload contains the following fields:

* ``max_reading_range_temp``, ``min_reading_range_temp`` - the range of reading
  values.
* ``reading_celsius`` - the current reading in degrees Celsius.
* ``sensor_number`` - the number of the temperature sensor.
* ``physical_context`` - the context of the sensor, usually reflecting its
  location, such as ``CPU``, ``Memory``, ``Intake``, ``PowerSupply`` or
  ``SystemBoard``. Can also be ``null``.

Each ``Power`` payload contains the following fields:

* ``power_capacity_watts``, ``line_input_voltage``, ``last_power_output_watts``
* ``serial_number`` - the serial number of the power source.
* ``state`` - the power source state: ``enabled``, ``absent`` (``null`` if
  unknown).
* ``health`` - the power source health status: ``ok``, ``warning``,
  ``critical`` (``null`` if unknown).

Each ``Drive`` payload contains the following fields:

* ``name`` - the drive name in the BMC (this is **not** a Linux device name
  like ``/dev/sda``).
* ``model`` - the drive model (if known).
* ``capacity_bytes`` - the drive capacity in bytes.
* ``state`` - the drive state: ``enabled``, ``absent`` (``null`` if unknown).
* ``health`` - the drive health status: ``ok``, ``warning``, ``critical``
  (``null`` if unknown).

.. note::
   Drive payloads are often not available on real hardware.

.. warning::
   Metrics collection works by polling several Redfish endpoints on the target
   BMC. Some older BMC implementations may have hard rate limits or misbehave
   under load. If this is the case for you, you need to reduce the metrics
   collection frequency or completely disable it.

Example (Dell)
--------------

.. code-block:: json

    {
        "message_id": "578628d2-9967-4d33-97ca-7e7c27a76abc",
        "publisher_id": "conductor-1.example.com",
        "event_type": "hardware.redfish.metrics",
        "priority": "INFO",
        "payload": {
            "message_id": "60653d54-87aa-43b8-a4ed-96d568dd4e96",
            "instance_uuid": null,
            "node_uuid": "aea161dc-2e96-4535-b003-ca70a4a7bb6d",
            "timestamp": "2023-10-22T15:50:26.841964",
            "node_name": "dell-430",
            "event_type": "hardware.redfish.metrics.update",
            "payload": {
                "Fan": {
                    "0x17||Fan.Embedded.1A@System.Embedded.1": {
                        "identity": "0x17||Fan.Embedded.1A",
                        "max_reading_range": null,
                        "min_reading_range": 720,
                        "reading": 1680,
                        "reading_units": "RPM",
                        "serial_number": null,
                        "physical_context": "SystemBoard",
                        "state": "enabled",
                        "health": "ok"
                    },
                    "0x17||Fan.Embedded.2A@System.Embedded.1": {
                        "identity": "0x17||Fan.Embedded.2A",
                        "max_reading_range": null,
                        "min_reading_range": 720,
                        "reading": 3120,
                        "reading_units": "RPM",
                        "serial_number": null,
                        "physical_context": "SystemBoard",
                        "state": "enabled",
                        "health": "ok"
                    },
                    "0x17||Fan.Embedded.2B@System.Embedded.1": {
                        "identity": "0x17||Fan.Embedded.2B",
                        "max_reading_range": null,
                        "min_reading_range": 720,
                        "reading": 3000,
                        "reading_units": "RPM",
                        "serial_number": null,
                        "physical_context": "SystemBoard",
                        "state": "enabled",
                        "health": "ok"
                    }
                },
                "Temperature": {
                    "iDRAC.Embedded.1#SystemBoardInletTemp@System.Embedded.1": {
                        "identity": "iDRAC.Embedded.1#SystemBoardInletTemp",
                        "max_reading_range_temp": 47,
                        "min_reading_range_temp": -7,
                        "reading_celsius": 28,
                        "physical_context": "SystemBoard",
                        "sensor_number": 4,
                        "state": "enabled",
                        "health": "ok"
                    },
                    "iDRAC.Embedded.1#CPU1Temp@System.Embedded.1": {
                        "identity": "iDRAC.Embedded.1#CPU1Temp",
                        "max_reading_range_temp": 90,
                        "min_reading_range_temp": 3,
                        "reading_celsius": 63,
                        "physical_context": "CPU",
                        "sensor_number": 14,
                        "state": "enabled",
                        "health": "ok"
                    }
                },
                "Power": {
                    "PSU.Slot.1:Power@System.Embedded.1": {
                        "power_capacity_watts": null,
                        "line_input_voltage": 206,
                        "last_power_output_watts": null,
                        "serial_number": "CNLOD0075324D7",
                        "state": "enabled",
                        "health": "ok"
                    },
                    "PSU.Slot.2:Power@System.Embedded.1": {
                        "power_capacity_watts": null,
                        "line_input_voltage": null,
                        "last_power_output_watts": null,
                        "serial_number": "CNLOD0075324E5",
                        "state": null,
                        "health": "critical"
                    }
                },
                "Drive": {
                    "Solid State Disk 0:1:0:RAID.Integrated.1-1@System.Embedded.1": {
                        "name": "Solid State Disk 0:1:0",
                        "capacity_bytes": 479559942144,
                        "state": "enabled",
                        "health": "ok"
                    },
                    "Physical Disk 0:1:1:RAID.Integrated.1-1@System.Embedded.1": {
                        "name": "Physical Disk 0:1:1",
                        "capacity_bytes": 1799725514752,
                        "state": "enabled",
                        "health": "ok"
                    },
                    "Physical Disk 0:1:2:RAID.Integrated.1-1@System.Embedded.1": {
                        "name": "Physical Disk 0:1:2",
                        "capacity_bytes": 1799725514752,
                        "state": "enabled",
                        "health": "ok"
                    },
                    "Backplane 1 on Connector 0 of Integrated RAID Controller 1:RAID.Integrated.1-1@System.Embedded.1": {
                        "name": "Backplane 1 on Connector 0 of Integrated RAID Controller 1",
                        "capacity_bytes": null,
                        "state": "enabled",
                        "health": "ok"
                    }
                }
            }
        },
        "timestamp": "2023-10-22 15:50:36.700458"
    }
