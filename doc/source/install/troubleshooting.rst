.. _troubleshooting-install:

===============
Troubleshooting
===============

Once all the services are running and configured properly, and a node has been
enrolled with the Bare Metal service and is in the ``available`` provision
state, the Compute service should detect the node
as an available resource and expose it to the scheduler.

.. note::
   There is a delay, and it may take up to a minute (one periodic task cycle)
   for the Compute service to recognize any changes in the Bare Metal service's
   resources (both additions and deletions).

In addition to watching ``nova-compute`` log files, you can see the available
resources by looking at the list of Compute hypervisors. The resources reported
therein should match the bare metal node properties, and the Compute service flavor.

Here is an example set of commands to compare the resources in Compute
service and Bare Metal service::

    $ baremetal node list
    +--------------------------------------+---------------+-------------+--------------------+-------------+
    | UUID                                 | Instance UUID | Power State | Provisioning State | Maintenance |
    +--------------------------------------+---------------+-------------+--------------------+-------------+
    | 86a2b1bb-8b29-4964-a817-f90031debddb | None          | power off   | available          | False       |
    +--------------------------------------+---------------+-------------+--------------------+-------------+

    $ baremetal node show 86a2b1bb-8b29-4964-a817-f90031debddb
    +------------------------+----------------------------------------------------------------------+
    | Property               | Value                                                                |
    +------------------------+----------------------------------------------------------------------+
    | instance_uuid          | None                                                                 |
    | properties             | {u'memory_mb': u'1024', u'cpu_arch': u'x86_64', u'local_gb': u'10'}  |
    | maintenance            | False                                                                |
    | driver_info            | { [SNIP] }                                                           |
    | extra                  | {}                                                                   |
    | last_error             | None                                                                 |
    | created_at             | 2014-11-20T23:57:03+00:00                                            |
    | target_provision_state | None                                                                 |
    | driver                 | ipmi                                                                 |
    | updated_at             | 2014-11-21T00:47:34+00:00                                            |
    | instance_info          | {}                                                                   |
    | chassis_uuid           | 7b49bbc5-2eb7-4269-b6ea-3f1a51448a59                                 |
    | provision_state        | available                                                            |
    | reservation            | None                                                                 |
    | power_state            | power off                                                            |
    | console_enabled        | False                                                                |
    | uuid                   | 86a2b1bb-8b29-4964-a817-f90031debddb                                 |
    +------------------------+----------------------------------------------------------------------+

    $ nova hypervisor-list
    +--------------------------------------+--------------------------------------+-------+---------+
    | ID                                   | Hypervisor hostname                  | State | Status  |
    +--------------------------------------+--------------------------------------+-------+---------+
    | 584cfdc8-9afd-4fbb-82ef-9ff25e1ad3f3 | 86a2b1bb-8b29-4964-a817-f90031debddb | up    | enabled |
    +--------------------------------------+--------------------------------------+-------+---------+

    $ nova hypervisor-show 584cfdc8-9afd-4fbb-82ef-9ff25e1ad3f3
    +-------------------------+--------------------------------------+
    | Property                | Value                                |
    +-------------------------+--------------------------------------+
    | cpu_info                | baremetal cpu                        |
    | current_workload        | 0                                    |
    | disk_available_least    | -                                    |
    | free_disk_gb            | 10                                   |
    | free_ram_mb             | 1024                                 |
    | host_ip                 | [ SNIP ]                             |
    | hypervisor_hostname     | 86a2b1bb-8b29-4964-a817-f90031debddb |
    | hypervisor_type         | ironic                               |
    | hypervisor_version      | 1                                    |
    | id                      | 1                                    |
    | local_gb                | 10                                   |
    | local_gb_used           | 0                                    |
    | memory_mb               | 1024                                 |
    | memory_mb_used          | 0                                    |
    | running_vms             | 0                                    |
    | service_disabled_reason | -                                    |
    | service_host            | my-test-host                         |
    | service_id              | 6                                    |
    | state                   | up                                   |
    | status                  | enabled                              |
    | vcpus                   | 1                                    |
    | vcpus_used              | 0                                    |
    +-------------------------+--------------------------------------+

.. _maintenance_mode:

Maintenance mode
----------------
Maintenance mode may be used if you need to take a node out of the resource
pool. Putting a node in maintenance mode will prevent Bare Metal service from
executing periodic tasks associated with the node. This will also prevent
Compute service from placing a tenant instance on the node by not exposing
the node to the nova scheduler. Nodes can be placed into maintenance mode
with the following command.
::

    $ baremetal node maintenance set $NODE_UUID

A maintenance reason may be included with the optional ``--reason`` command
line option. This is a free form text field that will be displayed in the
``maintenance_reason`` section of the ``node show`` command.

::

    $ baremetal node maintenance set $UUID --reason "Need to add ram."

    $ baremetal node show $UUID

    +------------------------+--------------------------------------+
    | Property               | Value                                |
    +------------------------+--------------------------------------+
    | target_power_state     | None                                 |
    | extra                  | {}                                   |
    | last_error             | None                                 |
    | updated_at             | 2015-04-27T15:43:58+00:00            |
    | maintenance_reason     | Need to add ram.                     |
    | ...                    | ...                                  |
    | maintenance            | True                                 |
    | ...                    | ...                                  |
    +------------------------+--------------------------------------+

To remove maintenance mode and clear any ``maintenance_reason`` use the
following command.
::

    $ baremetal node maintenance unset $NODE_UUID
