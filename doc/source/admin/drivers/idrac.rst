============
iDRAC driver
============

Overview
========

iDRAC_ hardware is supported by the ``idrac`` hardware type. It is also
supported by the standard ``ipmi`` hardware type, though with a smaller
feature set.

.. TODO(dtantsur): supported hardware

Enabling
========

The ``idrac`` hardware type requires the ``python-dracclient`` library to be
installed, for example::

    sudo pip install 'python-dracclient>=1.5.0,<3.0.0'

To enable the ``idrac`` hardware type, add the following to your
``/etc/ironic/ironic.conf``:

.. code-block:: ini

    [DEFAULT]
    enabled_hardware_types=idrac
    enabled_management_interfaces=idrac
    enabled_power_interfaces=idrac

To enable all optional features (inspection, RAID and vendor passthru), use
the following configuration:

.. code-block:: ini

    [DEFAULT]
    enabled_hardware_types=idrac
    enabled_inspect_interfaces=idrac
    enabled_management_interfaces=idrac
    enabled_power_interfaces=idrac
    enabled_raid_interfaces=idrac
    enabled_vendor_interfaces=idrac

Enrolling
=========

The following command will enroll a bare metal node with the ``idrac``
hardware type::

    openstack baremetal node create --driver idrac \
        --driver-info drac_address=drac.host \
        --driver-info drac_username=user \
        --driver-info drac_password=pa$$w0rd

.. TODO(dtantsur): describe RAID support and inspection

Known Issues
============

Nodes go into maintenance mode
------------------------------

After some period of time, nodes managed by the ``idrac`` hardware type may go
into maintenance mode in Ironic. This issue can be worked around by changing
the Ironic power state poll interval to 70 seconds. See
``[conductor]sync_power_state_interval`` in ``/etc/ironic/ironic.conf``.

.. _iDRAC: https://www.dell.com/support/manuals/us/en/15/openmanage-software-9.0.1/om_9.0.1_support_matrix/supported-integrated-dell-remote-access-controllers-and-solutions?guid=guid-07259e0b-a788-4a78-8f40-d46ef06a7697&lang=en-us
