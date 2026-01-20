===================
Hardware Inspection
===================

Overview
--------

Inspection allows Bare Metal service to discover required node properties
once required ``driver_info`` fields (for example, IPMI credentials) are set
by an operator. Inspection will also create the Bare Metal service ports for the
discovered ethernet MACs.

There are two kinds of inspection supported by Bare Metal service:

#. Out-of-band inspection is currently implemented by several hardware types,
   including ``redfish``, ``ilo``, ``idrac`` and ``irmc``.

#. In-band inspection, also known as Agent inspection
   utilizing Ironic Python Agent to collect information.

The node should be in the ``manageable`` state before inspection is initiated.
If it is in the ``enroll`` or ``available`` state, move it to ``manageable``
first::

    baremetal node manage <node_UUID>

Then inspection can be initiated using the following command::

    baremetal node inspect <node_UUID>

Functionality
-------------

.. toctree::
   :maxdepth: 2

   discovery
   data
   hooks
   rules
   capabilities
   managed
   pxe_filter
   migration
   copy-inspection-data-swift

Agent Inspection
----------------

Agent inspection (also known as in-band inspection) involves booting a ramdisk
on the target node and fetching information directly from it. This process is
more fragile and time-consuming than the out-of-band inspection, but it is not
vendor-specific and works across a wide range of hardware.

.. note::
   The implementation described in this document is not 100% compatible with
   the previous one (based on ironic-inspector). Check the documentation and
   the release notes for which features are currently available.

Configuration
~~~~~~~~~~~~~

Agent inspection is supported by all hardware types. The ``agent``
*inspect* interface has to be enabled to use it:

.. code-block:: ini

    [DEFAULT]
    enabled_inspect_interfaces = agent,redfish,no-inspect

You can make ``agent`` the default if you want all nodes to use it automatically:

.. code-block:: ini

    [DEFAULT]
    default_inspect_interface = agent

Of course, you can configure ``agent`` per node:

.. code-block:: console

   $ baremetal node set --inspect-interface agent <NODE>
