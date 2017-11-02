=============
iDRAC drivers
=============

Overview
========

iDRAC_ hardware is supported by the ``idrac`` hardware type and the following
classic drivers:

* ``pxe_drac`` (using out-of-band inspection)
* ``pxe_drac_inspector`` (using in-band inspection via **ironic-inspector**)

It is also supported by the standard ``ipmi`` hardware type, though with
a smaller feature set.

.. TODO(dtantsur): supported hardware

Enabling
========

All iDRAC drivers require the ``python-dracclient`` library to be installed,
for example::

    sudo pip install 'python-dracclient>=1.3.0'

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
        --driver-info drac_address=http://drac.host \
        --driver-info drac_username=user \
        --driver-info drac_password=pa$$w0rd

.. TODO(dtantsur): describe RAID support and inspection

.. _iDRAC: http://www.dell.com/learn/us/en/15/solutions/integrated-dell-remote-access-controller-idrac
