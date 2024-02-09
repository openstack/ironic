Configuring IPMI support
------------------------

Installing ipmitool command
~~~~~~~~~~~~~~~~~~~~~~~~~~~

To enable one of the drivers that use IPMI_ protocol for power and management
actions (for example, ``ipmi``), the ``ipmitool`` command must be present on
the service node(s) where ``ironic-conductor`` is running. On most distros, it
is provided as part of the ``ipmitool`` package. Source code is available at
http://ipmitool.sourceforge.net/.

.. warning::
    Certain distros, notably Mac OS X and SLES, install ``openipmi``
    instead of ``ipmitool`` by default. This driver is not compatible with
    ``openipmi`` as it relies on error handling options not provided by
    this tool.

Please refer to the :doc:`/admin/drivers/ipmitool` for information on how to
configure and use IPMItool-based drivers.

Configuring hardware
~~~~~~~~~~~~~~~~~~~~

IPMI is a relatively old protocol and may require additional set up on the
hardware side that the Bare Metal service cannot do automatically:

#. Make sure IPMI is enabled and the account you use have the permissions
   to change power and boot devices. By default the administrator rights are
   expected, you can change it: see :ref:`ipmi-priv-level`.

#. Make sure the cipher suites are configured for maximum security. Suite 17 is
   recommended, 3 can be used if it's not available. Cipher suite 0 **must** be
   disabled as it provides unauthenticated access to the BMC.

   .. seealso:: :ref:`ipmi-cipher-suites`

#. Make sure the boot mode correspond to the expected boot mode on the node
   (see :ref:`boot_mode_support`). Some hardware is able to change the boot
   mode to the requested by Ironic, some does not.

Validation and troubleshooting
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Check that you can connect to, and authenticate with, the IPMI
controller in your bare metal server by running ``ipmitool``::

    ipmitool -I lanplus -H <ip-address> -U <username> -P <password> chassis power status

where ``<ip-address>`` is the IP of the IPMI controller you want to access.
This is not the bare metal node's main IP. The IPMI controller should have
its own unique IP.

If the above command doesn't return the power status of the
bare metal server, check that

- ``ipmitool`` is installed and is available via the ``$PATH`` environment
  variable.
- The IPMI controller on your bare metal server is turned on.
- The IPMI controller credentials and IP address passed in the command
  are correct.
- The conductor node has a route to the IPMI controller. This can be
  checked by just pinging the IPMI controller IP from the conductor
  node.

IPMI configuration
~~~~~~~~~~~~~~~~~~

If there are slow or unresponsive BMCs in the environment, the
``min_command_interval`` configuration option in the ``[ipmi]`` section may
need to be raised. The default is fairly conservative, as setting this timeout
too low can cause older BMCs to crash and require a hard-reset.

.. _ipmi-sensor-data:

Collecting sensor data
~~~~~~~~~~~~~~~~~~~~~~

Bare Metal service supports sending IPMI sensor data to Telemetry with
certain hardware types, such as ``ipmi``, ``ilo`` and ``irmc``.  By default,
support for sending IPMI sensor data to Telemetry is disabled. If you want
to enable it, you should make the following two changes in ``ironic.conf``:

.. code-block:: ini

    [conductor]
    send_sensor_data = true
    [oslo_messaging_notifications]
    driver = messagingv2

If you want to customize the sensor types which will be sent to Telemetry,
change the ``send_sensor_data_types`` option. For example, the below
settings will send information about temperature, fan, voltage from sensors
to the Telemetry service:

.. code-block:: ini

    send_sensor_data_types=Temperature,Fan,Voltage

Supported sensor types are defined by the Telemetry service, currently
these are ``Temperature``, ``Fan``, ``Voltage``, ``Current``.
Special value ``All`` (the default) designates all supported sensor types.

.. _IPMI: https://en.wikipedia.org/wiki/Intelligent_Platform_Management_Interface
