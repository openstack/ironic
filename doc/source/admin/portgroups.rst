===================
Port groups support
===================

The Bare Metal service supports static configuration of port groups (bonds) in
the instances via configdrive. See `kernel documentation on bonding`_ to see
why it may be useful and how it is setup in linux. The sections below describe
how to make use of them in the Bare Metal service.

Switch-side configuration
-------------------------

If port groups are desired in the ironic deployment, they need to be configured
on the switches. It needs to be done manually, and the mode and properties
configured on the switch have to correspond to the mode and properties that
will be configured on the ironic side, as bonding mode and properties may be
named differently on your switch, or have possible values different from the
ones described in `kernel documentation on bonding`_. Please refer to your
switch configuration documentation for more details.

Provisioning and cleaning cannot make use of port groups if they need to boot
the deployment ramdisk via (i)PXE. If your switches or desired port group
configuration do not support port group fallback, which will allow port group
members to be used by themselves, you need to set port group's
``standalone_ports_supported`` value to be ``False`` in ironic, as it is
``True`` by default.

Physical networks
-----------------

If any port in a port group has a physical network, then all ports in
that port group must have the same physical network.

In order to change the physical network of the ports in a port group, all ports
must first be removed from the port group, before changing their physical
networks (to the same value), then adding them back to the port group.

See :ref:`physical networks <multitenancy-physnets>` for further information on
using physical networks in the Bare Metal service.

Port groups configuration in the Bare Metal service
---------------------------------------------------

Port group configuration is supported in ironic API microversions 1.26, the
CLI commands below specify it for completeness.

#. When creating a port group, the node to which it belongs must be specified,
   along with, optionally, its name, address, mode, properties, and if it
   supports fallback to standalone ports::

    baremetal port group create \
    --node $NODE_UUID --name test --address fa:ab:25:48:fd:ba --mode 802.3ad \
    --property miimon=100 --property xmit_hash_policy="layer2+3" \
    --support-standalone-ports

   A port group can also be updated with ``baremetal port group set``
   command, see its help for more details.

   If an address is not specified, the port group address on the deployed
   instance will be the same as the address of the neutron port that is
   attached to the port group. If the neutron port is not attached, the port
   group will not be configured.

   .. note::

      In standalone mode, port groups have to be configured manually. It can
      be done either statically inside the image, or by generating the
      configdrive and adding it to the node's ``instance_info``. For more
      information on how to configure bonding via configdrive, refer to
      `cloud-init documentation <https://cloudinit.readthedocs.io/en/latest/topics/datasources/configdrive.html#version-2>`_
      and `code <https://git.launchpad.net/cloud-init/tree/cloudinit>`_.
      cloud-init version 0.7.7 or later is required for bonding configuration
      to work.

      The following is a simple sample for configuring bonding via configdrive:

      When booting an instance, it needs to add user-data file for configuring
      bonding via ``--user-data`` option. For example:

      .. code-block:: json

          {
            "networks": [
              {
                "type": "physical",
                "name": "eth0",
                "mac_address": "fa:ab:25:48:fd:ba"
              },
              {
                "type": "physical",
                "name": "eth1",
                "mac_address": "fa:ab:25:48:fd:ab"
              },
              {
                "type": "bond",
                "name": "bond0",
                "bond_interfaces": [
                  "eth0", "eth1"
                  ],
                  "mode": "active-backup"
              }
            ]
          }

      If the port group's address is not explicitly set in standalone mode, it
      will be set automatically by the process described in
      `kernel documentation on bonding`_.

   During interface attachment, port groups have higher priority than ports,
   so they will be used first. (It is not yet possible to specify which one is
   desired, a port group or a port, in an interface attachment request). Port
   groups that don't have any ports will be ignored.

   The mode and properties values are described in the
   `kernel documentation on bonding`_. The default port group mode is
   ``active-backup``, and this default can be changed by setting the
   ``[DEFAULT]default_portgroup_mode`` configuration option in the ironic API
   service configuration file.

#. Associate ports with the created port group.

   It can be done on port creation::

     baremetal port create \
     --node $NODE_UUID --address fa:ab:25:48:fd:ba --port-group test

   Or by updating an existing port::

     baremetal port set $PORT_UUID --port-group $PORT_GROUP_UUID

   When updating a port, the node associated with the port has to be in
   ``enroll``, ``manageable``, or ``inspecting`` states. A port group can have
   the same or different address as individual ports.

#. Boot an instance (or node directly, in case of using standalone ironic)
   providing an image that has cloud-init version 0.7.7 or later and supports
   bonding.

When the deployment is done, you can check that the port group is set up
properly by running the following command in the instance::

  cat /proc/net/bonding/bondX

where ``X`` is a number autogenerated by cloud-init for each configured port
group, in no particular order. It starts with 0 and increments by 1 for every
configured port group.

.. _`kernel documentation on bonding`: https://www.kernel.org/doc/Documentation/networking/bonding.txt

Link aggregation/teaming on windows
-----------------------------------

Portgroups are supported for Windows Server images, which can created by
:ref:`building_image_windows` instruction.

You can customise an instance after it is launched along with
`script file
<https://opendev.org/openstack/ironic/src/branch/master/tools/link_aggregation_on_windows.ps1>`_ in
``Configuration`` of ``Instance`` and selected ``Configuration Drive`` option.
Then ironic virt driver will generate network metadata and add all the
additional information, such as bond mode, transmit hash policy,
MII link monitoring interval, and of which links the bond consists.
The information in InstanceMetadata will be used afterwards to generate
the config drive.
