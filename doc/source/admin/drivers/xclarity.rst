===============
XClarity driver
===============

Overview
========

The ``xclarity`` driver is targeted for IMM 2.0 and IMM 3.0 managed Lenovo
servers. The xclarity hardware type enables the user to take advantage of
`XClarity Manager`_ by using the `XClarity Python Client`_.

Prerequisites
=============

* The XClarity Client library should be installed on the ironic conductor
  node(s).

  For example, it can be installed with ``pip``::

      sudo pip install python-xclarityclient

Enabling the XClarity driver
============================

#. Add ``xclarity`` to the list of ``enabled_hardware_types``,
   ``enabled_power_interfaces`` and ``enabled_management_interfaces``
   in ``/etc/ironic/ironic.conf``. For example::

    [DEFAULT]
    ...
    enabled_hardware_types = ipmi,xclarity
    enabled_power_interfaces = ipmitool,xclarity
    enabled_management_interfaces = ipmitool,xclarity

#. Restart the ironic conductor service::

    sudo service ironic-conductor restart

    # Or, for RDO:
    sudo systemctl restart openstack-ironic-conductor

Registering a node with the XClarity driver
===========================================

Nodes configured to use the driver should have the ``driver`` property
set to ``xclarity``.

The following properties are specified in the node's ``driver_info``
field and are required:

- ``xclarity_manager_ip``: The IP address of the XClarity Controller.
- ``xclarity_username``: User account with admin/server-profile access
  privilege to the XClarity Controller.
- ``xclarity_password``: User account password corresponding to the
  xclarity_username to the XClarity Controller.
- ``xclarity_hardware_id``: The hardware ID of the XClarity managed server.

The ``baremetal node create`` command can be used to enroll
a node with the ``xclarity`` driver. For example:

.. code-block:: bash

  baremetal node create --driver xclarity \
    --driver-info xclarity_manager_ip=https://10.240.217.101 \
    --driver-info xclarity_username=admin \
    --driver-info xclarity_password=password \
    --driver-info xclarity_hardware_id=hardware_id

For more information about enrolling nodes see :ref:`enrollment`
in the install guide.

.. _`XClarity Manager`: http://www3.lenovo.com/us/en/data-center/software/systems-management/xclarity/
.. _`XClarity Python Client`: http://pypi.org/project/python-xclarityclient/
