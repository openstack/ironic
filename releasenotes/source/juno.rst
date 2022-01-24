=============================================
Juno Series (2014.2 - 2014.2.1) Release Notes
=============================================

Key Features
============
* The Nova "ironic" driver is in the Nova code base. In Icehouse, the Nova "ironic" driver was not in the Nova code base. Now that it is in the Nova code base, it is no longer necessary to install Ironic on the nova-compute hosts.
  * nova rebuild is supported by the nova.virt.ironic driver
  * however, the optional --preserve-ephemeral flag is not supported by "agent"-based deploy drivers.
* IPMI sensor data can be emitted (eg to Ceilometer)
* New hardware drivers: DRAC power & management driver, iLO power & virtual-media deploy driver, SNMP power driver, iBoot PDU power driver
* New "agent" family of deploy drivers
* Neutron dependency has been removed.
  * It is possible to use an external static DHCP configuration with agent-based drivers (eg, agent_ipmitool) or no DHCP at all with iLO-based drivers (eg, agent_ilo and iscsi_ilo)
* UEFI and iPXE boot support is available in some drivers
* Serial-over-LAN console is supported. The IPMItool and NativeIPMI drivers support serial console.

Known Issues
============

* IPMI passwords are visible to users with cloud admin privileges, via Ironic's API.
* Running more than one nova-compute process is not officially supported. While Ironic does include a ClusteredComputeManager, which allows running more than one nova-compute process with Ironic, it should be considered experimental and has many known problems.
* Drivers using the "agent" deploy mechanism differ in their functionality from those using the "pxe" deploy mechanism in the following ways:
  * agent requires a whole-disk image, and does not support "rebuild --preserve-ephemeral"; "pxe" requires a partition image, and supports "rebuild --preserve-ephemeral"
  * nodes deployed by the "agent" drivers will boot from the local disk; nodes deployed by the "pxe" drivers can not boot from local disk, and will always require a net boot (whether via pxe, ipxe, or virtual-media)
