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
   ``enabled_power_interfaces`` and ``enabled_management_interfaces``
   in ``/etc/ironic/ironic.conf``. For example::

    [DEFAULT]
    ...
    enabled_hardware_types = ipmi,redfish
    enabled_power_interfaces = ipmitool,redfish
    enabled_management_interfaces = ipmitool,redfish

#. Restart the ironic conductor service::

    sudo service ironic-conductor restart

    # Or, for RDO:
    sudo systemctl restart openstack-ironic-conductor

Registering a node with the Redfish driver
===========================================

Nodes configured to use the driver should have the ``driver`` property
set to ``redfish``.

The following properties are required and must be specified in the node's
``driver_info`` field:

- ``redfish_address``: The URL address to the Redfish controller. It should
                       include scheme and authority portion of the URL.
                       For example: https://mgmt.vendor.com

- ``redfish_system_id``: The canonical path to the System resource that
                         the driver will interact with. It should include
                         the root service, version and the unique
                         resource path to the System. For example:
                         /redfish/v1/Systems/1

- ``redfish_username``: User account with admin/server-profile access
                        privilege

- ``redfish_password``: User account password

By default, if the ``redfish_address`` is using **https** the driver
will use a secure (TLS_) connection when talking to the Redfish
controller and for that it will try to verify the certificates present
on the ironic conductor node. This behavior can be changed or disabled
(**not recommended**) by setting the ``redfish_verify_ca`` property as:

- ``redfish_verify_ca``: Path to a certificate file or directory with
  trusted certificates

or

- ``redfish_verify_ca``: False (Disable verifying TLS_)

The ``openstack baremetal node create`` command can be used to enroll
a node with the ``redfish`` driver. For example:

.. code-block:: bash

  openstack baremetal node create --driver redfish --driver-info \
    redfish_address=https://example.com --driver-info \
    redfish_system_id=/redfish/v1/Systems/CX34R87 --driver-info \
    redfish_username=admin --driver-info redfish_password=password

For more information about enrolling nodes see `Enrolling a node`_
in the install guide.

.. _Redfish: http://redfish.dmtf.org/
.. _Sushy: https://git.openstack.org/cgit/openstack/sushy
.. _TLS: https://en.wikipedia.org/wiki/Transport_Layer_Security
.. _`Enrolling a node`: http://docs.openstack.org/project-install-guide/baremetal/draft/enrollment.html#enrolling-a-node
