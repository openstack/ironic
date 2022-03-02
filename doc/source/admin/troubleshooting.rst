.. _troubleshooting:

======================
Troubleshooting Ironic
======================

Nova returns "No valid host was found" Error
============================================

Sometimes Nova Conductor log file "nova-conductor.log" or a message returned
from Nova API contains the following error::

    NoValidHost: No valid host was found. There are not enough hosts available.

"No valid host was found" means that the Nova Scheduler could not find a bare
metal node suitable for booting the new instance.

This in turn usually means some mismatch between resources that Nova expects
to find and resources that Ironic advertised to Nova.

A few things should be checked in this case:

#. Make sure that enough nodes are in ``available`` state, not in
   maintenance mode and not already used by an existing instance.
   Check with the following command::

       baremetal node list --provision-state available --no-maintenance --unassociated

   If this command does not show enough nodes, use generic ``baremetal
   node list`` to check other nodes. For example, nodes in ``manageable`` state
   should be made available::

       baremetal node provide <IRONIC NODE>

   The Bare metal service automatically puts a node in maintenance mode if
   there are issues with accessing its management interface. See
   :ref:`power-fault` for details.

   The ``node validate`` command can be used to verify that all required fields
   are present. The following command should not return anything::

       baremetal node validate <IRONIC NODE> | grep -E '(power|management)\W*False'

   Maintenance mode will be also set on a node if automated cleaning has
   failed for it previously.

#. Make sure that you have Compute services running and enabled::

       $ openstack compute service list --service nova-compute
       +----+--------------+-------------+------+---------+-------+----------------------------+
       | ID | Binary       | Host        | Zone | Status  | State | Updated At                 |
       +----+--------------+-------------+------+---------+-------+----------------------------+
       |  7 | nova-compute | example.com | nova | enabled | up    | 2017-09-04T13:14:03.000000 |
       +----+--------------+-------------+------+---------+-------+----------------------------+

   By default, a Compute service is disabled after 10 consecutive build
   failures on it. This is to ensure that new build requests are not routed to
   a broken Compute service. If it is the case, make sure to fix the source of
   the failures, then re-enable it::

       openstack compute service set --enable <COMPUTE HOST> nova-compute

#. Starting with the Pike release, check that all your nodes have the
   ``resource_class`` field set using the following command::

      baremetal node list --fields uuid name resource_class

   Then check that the flavor(s) are configured to request these resource
   classes via their properties::

       openstack flavor show <FLAVOR NAME> -f value -c properties

   For example, if your node has resource class ``baremetal-large``, it will
   be matched by a flavor with property ``resources:CUSTOM_BAREMETAL_LARGE``
   set to ``1``. See :doc:`/install/configure-nova-flavors` for more
   details on the correct configuration.

#. Upon scheduling, Nova will query the Placement API service for the
   available resource providers (in the case of Ironic: nodes with a given
   resource class). If placement does not have any allocation candidates for the
   requested resource class, the request will result in a "No valid host
   was found" error. It is hence sensible to check if Placement is aware of
   resource providers (nodes) for the requested resource class with::

       $ openstack allocation candidate list --resource CUSTOM_BAREMETAL_LARGE='1'
       +---+-----------------------------+--------------------------------------+-------------------------------+
       | # | allocation                  | resource provider                    | inventory used/capacity       |
       +---+-----------------------------+--------------------------------------+-------------------------------+
       | 1 | CUSTOM_BAREMETAL_LARGE=1    | 2f7b9c69-c1df-4e40-b94e-5821a4ea0453 | CUSTOM_BAREMETAL_LARGE=0/1    |
       +---+-----------------------------+--------------------------------------+-------------------------------+

   For Ironic, the resource provider is the UUID of the available Ironic node.
   If this command returns an empty list (or does not contain the targeted
   resource provider), the operator needs to understand first, why the resource
   tracker has not reported this provider to placement. Potential explanations
   include:

   * the resource tracker cycle has not finished yet and the resource provider
     will appear once it has (the time to finish the cycle scales linearly with
     the number of nodes the corresponding ``nova-compute`` service manages);

   * the node is in a state where the resource tracker does not consider it to
     be eligible for scheduling, e.g. when the node has ``maintenance`` set to
     ``True``; make sure the target nodes are in ``available`` and
     ``maintenance`` is ``False``;

#. If you do not use scheduling based on resource classes, then the node's
   properties must have been set either manually or via inspection.
   For each node with ``available`` state check that the ``properties``
   JSON field has valid values for the keys ``cpus``, ``cpu_arch``,
   ``memory_mb`` and ``local_gb``. Example of valid properties::

        $ baremetal node show <IRONIC NODE> --fields properties
        +------------+------------------------------------------------------------------------------------+
        | Property   | Value                                                                              |
        +------------+------------------------------------------------------------------------------------+
        | properties | {u'memory_mb': u'8192', u'cpu_arch': u'x86_64', u'local_gb': u'41', u'cpus': u'4'} |
        +------------+------------------------------------------------------------------------------------+

   .. warning::
       If you're using exact match filters in the Nova Scheduler, make sure
       the flavor and the node properties match exactly.

#. The Nova flavor that you are using does not match any properties of the
   available Ironic nodes. Use
   ::

        openstack flavor show <FLAVOR NAME>

   to compare. The extra specs in your flavor starting with ``capability:``
   should match ones in ``node.properties['capabilities']``.

   .. note::
      The format of capabilities is different in Nova and Ironic.
      E.g. in Nova flavor::

        $ openstack flavor show <FLAVOR NAME> -c properties
        +------------+----------------------------------+
        | Field      | Value                            |
        +------------+----------------------------------+
        | properties | capabilities:boot_option='local' |
        +------------+----------------------------------+

      But in Ironic node::

        $ baremetal node show <IRONIC NODE> --fields properties
        +------------+-----------------------------------------+
        | Property   | Value                                   |
        +------------+-----------------------------------------+
        | properties | {u'capabilities': u'boot_option:local'} |
        +------------+-----------------------------------------+

#. After making changes to nodes in Ironic, it takes time for those changes
   to propagate from Ironic to Nova. Check that
   ::

        openstack hypervisor stats show

   correctly shows total amount of resources in your system. You can also
   check ``openstack hypervisor show <IRONIC NODE>`` to see the status of
   individual Ironic nodes as reported to Nova.

#. Figure out which Nova Scheduler filter ruled out your nodes. Check the
   ``nova-scheduler`` logs for lines containing something like::

        Filter ComputeCapabilitiesFilter returned 0 hosts

   The name of the filter that removed the last hosts may give some hints on
   what exactly was not matched. See
   :nova-doc:`Nova filters documentation <filter_scheduler.html>`
   for more details.

#. If none of the above helped, check Ironic conductor log carefully to see
   if there are any conductor-related errors which are the root cause for
   "No valid host was found". If there are any "Error in deploy of node
   <IRONIC-NODE-UUID>: [Errno 28] ..." error messages in Ironic conductor
   log, it means the conductor run into a special error during deployment.
   So you can check the log carefully to fix or work around and then try
   again.

Patching the Deploy Ramdisk
===========================

When debugging a problem with deployment and/or inspection you may want to
quickly apply a change to the ramdisk to see if it helps. Of course you can
inject your code and/or SSH keys during the ramdisk build (depends on how
exactly you've built your ramdisk). But it's also possible to quickly modify
an already built ramdisk.

Create an empty directory and unpack the ramdisk content there:

.. code-block:: bash

    $ mkdir unpack
    $ cd unpack
    $ gzip -dc /path/to/the/ramdisk | cpio -id

The last command will result in the whole Linux file system tree unpacked in
the current directory. Now you can modify any files you want. The actual
location of the files will depend on the way you've built the ramdisk.

.. note::
    On a systemd-based system you can use the ``systemd-nspawn`` tool (from
    the ``systemd-container`` package) to create a lightweight container from
    the unpacked filesystem tree::

        $ sudo systemd-nspawn --directory /path/to/unpacked/ramdisk/ /bin/bash

    This will allow you to run commands within the filesystem, e.g. use package
    manager. If the ramdisk is also systemd-based, and you have login
    credentials set up, you can even boot a real ramdisk enviroment with

    ::

        $ sudo systemd-nspawn --directory /path/to/unpacked/ramdisk/ --boot

After you've done the modifications, pack the whole content of the current
directory back::

    $ find . | cpio -H newc -o | gzip -c > /path/to/the/new/ramdisk

.. note:: You don't need to modify the kernel (e.g.
          ``tinyipa-master.vmlinuz``), only the ramdisk part.

API Errors
==========

The `debug_tracebacks_in_api` config option may be set to return tracebacks
in the API response for all 4xx and 5xx errors.

.. _retrieve_deploy_ramdisk_logs:

Retrieving logs from the deploy ramdisk
=======================================

When troubleshooting deployments (specially in case of a deploy failure)
it's important to have access to the deploy ramdisk logs to be able to
identify the source of the problem. By default, Ironic will retrieve the
logs from the deploy ramdisk when the deployment fails and save it on the
local filesystem at ``/var/log/ironic/deploy``.

To change this behavior, operators can make the following changes to
``/etc/ironic/ironic.conf`` under the ``[agent]`` group:

* ``deploy_logs_collect``:  Whether Ironic should collect the deployment
  logs on deployment. Valid values for this option are:

  * ``on_failure`` (**default**): Retrieve the deployment logs upon a
    deployment failure.

  * ``always``: Always retrieve the deployment logs, even if the
    deployment succeed.

  * ``never``: Disable retrieving the deployment logs.

* ``deploy_logs_storage_backend``: The name of the storage backend where
  the logs will be stored. Valid values for this option are:

  * ``local`` (**default**): Store the logs in the local filesystem.

  * ``swift``: Store the logs in Swift.

* ``deploy_logs_local_path``: The path to the directory where the
  logs should be stored, used when the ``deploy_logs_storage_backend``
  is configured to ``local``. By default logs will be stored at
  **/var/log/ironic/deploy**.

* ``deploy_logs_swift_container``: The name of the Swift container to
  store the logs, used when the deploy_logs_storage_backend is configured to
  "swift". By default **ironic_deploy_logs_container**.

* ``deploy_logs_swift_days_to_expire``: Number of days before a log object
  is marked as expired in Swift. If None, the logs will be kept forever
  or until manually deleted. Used when the deploy_logs_storage_backend is
  configured to "swift". By default **30** days.

When the logs are collected, Ironic will store a *tar.gz* file containing
all the logs according to the ``deploy_logs_storage_backend``
configuration option. All log objects will be named with the following
pattern::

  <node>[_<instance-uuid>]_<timestamp yyyy-mm-dd-hh:mm:ss>.tar.gz

.. note::
   The *instance_uuid* field is not required for deploying a node when
   Ironic is configured to be used in standalone mode. If present it
   will be appended to the name.


Accessing the log data
----------------------

When storing in the local filesystem
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

When storing the logs in the local filesystem, the log files can
be found at the path configured in the ``deploy_logs_local_path``
configuration option. For example, to find the logs from the node
``5e9258c4-cfda-40b6-86e2-e192f523d668``:

.. code-block:: bash

   $ ls /var/log/ironic/deploy | grep 5e9258c4-cfda-40b6-86e2-e192f523d668
   5e9258c4-cfda-40b6-86e2-e192f523d668_88595d8a-6725-4471-8cd5-c0f3106b6898_2016-08-08-13:52:12.tar.gz
   5e9258c4-cfda-40b6-86e2-e192f523d668_db87f2c5-7a9a-48c2-9a76-604287257c1b_2016-08-08-14:07:25.tar.gz

.. note::
   When saving the logs to the filesystem, operators may want to enable
   some form of rotation for the logs to avoid disk space problems.


When storing in Swift
~~~~~~~~~~~~~~~~~~~~~

When using Swift, operators can associate the objects in the
container with the nodes in Ironic and search for the logs for the node
``5e9258c4-cfda-40b6-86e2-e192f523d668`` using the **prefix** parameter.
For example:

.. code-block:: bash

  $ swift list ironic_deploy_logs_container -p 5e9258c4-cfda-40b6-86e2-e192f523d668
  5e9258c4-cfda-40b6-86e2-e192f523d668_88595d8a-6725-4471-8cd5-c0f3106b6898_2016-08-08-13:52:12.tar.gz
  5e9258c4-cfda-40b6-86e2-e192f523d668_db87f2c5-7a9a-48c2-9a76-604287257c1b_2016-08-08-14:07:25.tar.gz

To download a specific log from Swift, do:

.. code-block:: bash

   $ swift download ironic_deploy_logs_container "5e9258c4-cfda-40b6-86e2-e192f523d668_db87f2c5-7a9a-48c2-9a76-604287257c1b_2016-08-08-14:07:25.tar.gz"
   5e9258c4-cfda-40b6-86e2-e192f523d668_db87f2c5-7a9a-48c2-9a76-604287257c1b_2016-08-08-14:07:25.tar.gz [auth 0.341s, headers 0.391s, total 0.391s, 0.531 MB/s]

The contents of the log file
~~~~~~~~~~~~~~~~~~~~~~~~~~~~

The log is just a ``.tar.gz`` file that can be extracted as:

.. code-block:: bash

   $ tar xvf <file path>


The contents of the file may differ slightly depending on the distribution
that the deploy ramdisk is using:

* For distributions using ``systemd`` there will be a file called
  **journal** which contains all the system logs collected via the
  ``journalctl`` command.

* For other distributions, the ramdisk will collect all the contents of
  the ``/var/log`` directory.

For all distributions, the log file will also contain the output of
the following commands (if present): ``ps``, ``df``, ``ip addr`` and
``iptables``.

Here's one example when extracting the content of a log file for a
distribution that uses ``systemd``:

.. code-block:: bash

   $ tar xvf 5e9258c4-cfda-40b6-86e2-e192f523d668_88595d8a-6725-4471-8cd5-c0f3106b6898_2016-08-08-13:52:12.tar.gz
   df
   ps
   journal
   ip_addr
   iptables

.. _troubleshooting-stp:

DHCP during PXE or iPXE is inconsistent or unreliable
=====================================================

This can be caused by the spanning tree protocol delay on some switches. The
delay prevents the switch port moving to forwarding mode during the nodes
attempts to PXE, so the packets never make it to the DHCP server. To resolve
this issue you should set the switch port that connects to your baremetal nodes
as an edge or PortFast type port. Configured in this way the switch port will
move to forwarding mode as soon as the link is established. An example on how to
do that for a Cisco Nexus switch is:

.. code-block:: bash

    $ config terminal
    $ (config) interface eth1/11
    $ (config-if) spanning-tree port type edge

Why does X issue occur when I am using LACP bonding with iPXE?
==============================================================

If you are using iPXE, an unfortunate aspect of its design and interaction
with networking is an automatic response as a Link Aggregation Control
Protocol (or LACP) peer to remote switches. iPXE does this for only the
single port which is used for network booting.

In theory, this may help establish the port link-state faster with some
switch vendors, but the official reasoning as far as the Ironic Developers
are aware is not documented for iPXE. The end result of this is that once
iPXE has stopped responding to LACP messages from the peer port, which
occurs as part of the process of booting a ramdisk and iPXE handing
over control to a full operating-system, switches typically begin a
timer to determine how to handle the failure. This is because,
depending on the mode of LACP, this can be interpreted as a switch or
network fabric failure.

This may demonstrate as any number of behaviors or issues from ramdisks
finding they are unable to acquire DHCP addresses over the network interface
to downloads abruptly stalling, to even minor issues such as LLDP port data
being unavailable in introspection.

Overall:

* Ironic's agent doesn't officially support LACP and the Ironic community
  generally believes this may cause more problems than it would solve.
  During the Victoria development cycle, we added retry logic for most
  actions in an attempt to navigate the worst-known default hold-down
  timers to help ensure a deployment does not fail due to a short-lived
  transitory network connectivity failure in the form of a switch port having
  moved to a temporary blocking state. Where applicable and possible,
  many of these patches have been backported to supported releases.
  These patches also require that the switchport has an eventual fallback to a
  non-bonded mode. If the port remains in a blocking state, then traffic will
  be unable to flow and the deployment is likely to time out.
* If you must use LACP, consider ``passive`` LACP negotiation settings
  in the network switch as opposed to ``active``. The difference being with
  passive the connected workload is likely a server where it should likely
  request the switch to establish the Link Aggregate. This is instead of
  being treated as if it's possibly another switch.
* Consult your switch vendor's support forums. Some vendors have recommended
  port settings for booting machines using iPXE with their switches.

IPMI errors
===========

When working with IPMI, several settings need to be enabled depending on vendors.

Enable IPMI over LAN
--------------------

Machines may not have IPMI access over LAN enabled by default. This could cause
the IPMI port to be unreachable through ipmitool, as shown:

.. code-block:: bash

    $ ipmitool -I lan -H ipmi_host -U ipmi_user -P ipmi_pass chassis power status
    Error: Unable to establish LAN session

To fix this, enable `IPMI over lan` setting using your BMC tool or web app.

Troubleshooting lanplus interface
---------------------------------

When working with lanplus interfaces, you may encounter the following error:

.. code-block:: bash

    $ ipmitool -I lanplus -H ipmi_host -U ipmi_user -P ipmi_pass power status
    Error in open session response message : insufficient resources for session
    Error: Unable to establish IPMI v2 / RMCP+ session

To fix that issue, please enable `RMCP+ Cipher Suite3 Configuration` setting
using your BMC tool or web app.

Why are my nodes stuck in a "-ing" state?
=========================================

The Ironic conductor uses states ending with ``ing`` as a signifier that
the conductor is actively working on something related to the node.

Often, this means there is an internal lock or ``reservation`` set on the node
and the conductor is downloading, uploading, or attempting to perform some
sort of Input/Output operation - see `Why does API return "Node is locked by
host"?`_ for details.

In the case the conductor gets stuck, these operations should timeout,
but there are cases in operating systems where operations are blocked until
completion. These sorts of operations can vary based on the specific
environment and operating configuration.

What can cause these sorts of failures?
---------------------------------------

Typical causes of such failures are going to be largely rooted in the concept
of ``iowait``, either in the form of downloading from a remote host or
reading or writing to the disk of the conductor. An operator can use the
`iostat <https://man7.org/linux/man-pages/man1/iostat.1.html>`_ tool to
identify the percentage of CPU time spent waiting on storage devices.

The fields that will be particularly important are the ``iowait``, ``await``,
and ``tps`` ones, which can be read about in the ``iostat`` manual page.

In the case of network file systems, for backing components such as image
caches or distributed ``tftpboot`` or ``httpboot`` folders, IO operations
failing on these can, depending on operating system and underlying client
settings, cause threads to be stuck in a blocking wait state, which is
realistically undetectable short the operating system logging connectivity
errors or even lock manager access errors.

For example with
`nfs <https://www.man7.org/linux/man-pages/man5/nfs.5.html>`_,
the underlying client recovery behavior, in terms of ``soft``, ``hard``,
``softreval``, ``nosoftreval``, will largely impact this behavior, but also
NFS server settings can impact this behavior. A solid sign that this is a
failure, is when an ``ls /path/to/nfs`` command hangs for a period of time.
In such cases, the Storage Administrator should be consulted and network
connectivity investigated for errors before trying to recover to
proceed.

The bad news for IO related failures
------------------------------------

If the node has a populated ``reservation`` field, and has not timed out or
proceeded to a ``fail`` state, then the conductor process will likely need to
be restarted. This is because the worker thread is hung with-in the conductor.

Manual intervention with-in Ironic's database is *not* advised to try and
"un-wedge" the machine in this state, and restarting the conductor is
encouraged.

.. note::
   Ironic's conductor, upon restart, clears reservations for nodes which
   were previously managed by the conductor before restart.

If a distributed or network file system is in use, it is highly recommended
that the operating system of the node running the conductor be rebooted as
the running conductor may not even be able to exit in the state of an IO
failure, again dependent upon site and server configuration.

File Size != Disk Size
----------------------

An easy to make misconception is that a 2.4 GB file means that only 2.4 GB
is written to disk. But if that file's virtual size is 20 GB, or 100 GB
things can become very problematic and extend the amount of time the node
spends in ``deploying`` and ``deploy wait`` states.

Again, these sorts of cases will depend upon the exact configuration of the
deployment, but hopefully these are areas where these actions can occur.

* Conversion to raw image files upon download to the conductor, from the
  ``[DEFAULT]force_raw_images`` option. Users using Glance may also experience
  issues here as the conductor will cache the image to be written which takes
  place when the ``[agent]image_download_source`` is set to ``http`` instead of
  ``swift``.

.. note::
   The QCOW2 image conversion utility does consume quite a bit of memory
   when converting images or writing them to the end storage device. This
   is because the files are not sequential in nature, and must be re-assembled
   from an internal block mapping. Internally Ironic limits this to 1GB
   of RAM. Operators performing large numbers of deployments may wish to
   disable raw images in these sorts of cases in order to minimize the
   conductor becoming a limiting factor due to memory and network IO.

Why are my nodes stuck in a "wait" state?
=========================================

The Ironic conductor uses states containing ``wait`` as a signifier that
the conductor is waiting for a callback from another component, such as
the Ironic Python Agent or the Inspector. If this feedback does not arrive,
the conductor will time out and the node will eventually move to a ``failed``
state. Depending on the configuration and the circumstances, however, a node
can stay in a ``wait`` state for a long time or even never time out. The list
of such wait states includes:

* ``clean wait`` for cleaning,
* ``inspect wait`` for introspection,
* ``rescue wait`` for rescueing, and
* ``wait call-back`` for deploying.

Communication issues between the conductor and the node
-------------------------------------------------------

One of the most common issues when nodes seem to be stuck in a wait state
occur when the node never received any instructions or does not react as
expected: the conductor moved the node to a wait state but the node will
never call back. Examples include wrong ciphers which will make ipmitool
get stuck or BMCs in a state where they accept commands, but don't do the
requested task (or only a part of it, like shutting off, but not starting).
It is useful in these cases to see via a ping or the console if and which
action the node is performing. If the node does not seem to react to the
requests sent be the conductor, it may be worthwhile to try the corresponding
action out-of-band, e.g. confirm that power on/off commands work when directly
sent to the BMC. The section on `IPMI errors`_. above gives some additional
points to check. In some situations, a BMC reset may be necessary.

Ironic Python Agent stuck
-------------------------

Nodes can also get remain in a wait state when the component the conductor is
waiting for gets stuck, e.g. when a hardware manager enters a loop or is
waiting for an event that is never happening. In these cases, it might be
helpful to connect to the IPA and inspect its logs, see the trouble shooting
guide of the :ironic-python-agent-doc:`ironic-python-agent (IPA) <>` on how
to do this.

Stopping the operation
----------------------

Cleaning, inspection and rescuing can be stopped while in ``clean wait``,
``inspect wait`` and ``rescue wait`` states using the ``abort`` command.
It will move the node to the corresponding failure state (``clean failed``,
``inspect failed`` or ``rescue failed``)::

    baremetal node abort <node>

Deploying can be aborted while in the ``wait call-back`` state  by starting an
undeploy (normally resulting in cleaning)::

    baremetal node undeploy <node>

See :doc:`/user/states` for more details.

.. note::
   Since the Bare Metal service is not doing anything actively in waiting
   states, the nodes are not moved to failed states on conductor restart.

Deployments fail with "failed to update MAC address"
====================================================

The design of the integration with the Networking service (neutron) is such
that once virtual ports have been created in the API, their MAC address must
be updated in order for the DHCP server to be able to appropriately reply.

This can sometimes result in errors being raised indicating that the MAC
address is already in use. This is because at some point in the past, a
virtual interface was orphaned either by accident or by some unexpected
glitch, and a previous entry is still present in Neutron.

This error looks something like this when reported in the ironic-conductor
log output.:

  Failed to update MAC address on Neutron port 305beda7-0dd0-4fec-b4d2-78b7aa4e8e6a.: MacAddressInUseClient: Unable to complete operation for network 1e252627-6223-4076-a2b9-6f56493c9bac. The mac address 52:54:00:7c:c4:56 is in use.

Because we have no idea about this entry, we fail the deployment process
as we can't make a number of assumptions in order to attempt to automatically
resolve the conflict.

How did I get here?
-------------------

Originally this was a fairly easy issue to encounter. The retry logic path
which resulted between the Orchestration (heat) and Compute (nova) services,
could sometimes result in additional un-necessary ports being created.

Bugs of this class have been largely resolved since the Rocky development
cycle. Since then, the way this can become encountered is due to Networking
(neutron) VIF attachments not being removed or deleted prior to deleting a
port in the Bare Metal service.

Ultimately, the key of this is that the port is being deleted. Under most
operating circumstances, there really is no need to delete the port, and
VIF attachments are stored on the port object, so deleting the port
*CAN* result in the VIF not being cleaned up from Neutron.

Under normal circumstances, when deleting ports, a node should be in a
stable state, and the node should not be provisioned. If the
``baremetal port delete`` command fails, this may indicate that
a known VIF is still attached. Generally if they are transitory from cleaning,
provisioning, rescuing, or even inspection, getting the node to the
``available`` state wil unblock your delete operation, that is unless there is
a tenant VIF attahment. In that case, the vif will need to be removed from
with-in the Bare Metal service using the
``baremetal node vif detach`` command.

A port can also be checked to see if there is a VIF attachment by consulting
the port's ``internal_info`` field.

.. warning::
   The ``maintenance`` flag can be used to force the node's port to be
   deleted, however this will disable any check that would normally block
   the user from issuing a delete and accidently orphaning the VIF attachment
   record.

How do I resolve this?
----------------------

Generally, you need to identify the port with the offending MAC address.
Example:

.. code-block:: console

  $ openstack port list --mac-address 52:54:00:7c:c4:56

From the command's output, you should be able to identify the ``id`` field.
Using that, you can delete the port. Example:

.. code-block:: console

  $ openstack port delete <id>

.. warning::
   Before deleting a port, you should always verify that it is no longer in
   use or no longer seems applicable/operable. If multiple deployments of
   the Bare Metal service with a single Neutron, the possibility that a
   inventory typo, or possibly even a duplicate MAC address exists, which
   could also produce the same basic error message.

My test VM image does not deploy -- mount point does not exist
==============================================================

What is likely occuring
-----------------------

The image attempting to be deployed likely is a partition image where
the file system that the user wishes to boot from lacks the required
folders, such as ``/dev`` and ``/proc``, which are required to install
a bootloader for a Linux OS image

It should be noted that similar errors can also occur with whole disk
images where we are attempting to setup the UEFI bootloader configuration.
That being said, in this case, the image is likely invalid or contains
an unexpected internal structure.

Users performing testing may choose something that they believe
will work based on it working for virtual machines. These images are often
attractive for testing as they are generic and include basic support
for establishing networking and possibly installing user keys.
Unfortunately, these images often lack drivers and firmware required for
many different types of physical hardware which makes using them
very problematic. Additionally, images such as `Cirros <https://download.cirros-cloud.net>`_
do not have any contents in the root filesystem (i.e. an empty filesystem),
as they are designed for the ``ramdisk`` to write the contents to disk upon
boot.

How do I not encounter this issue?
----------------------------------

We generally recommend using `diskimage-builder <https://docs.openstack.org/diskimage-builder>`_
or vendor supplied images. Centos, Ubuntu, Fedora, and Debian all publish
operating system images which do generally include drivers and firmware for
physical hardware. Many of these published "cloud" images, also support
auto-configuration of networking AND population of user keys.

Issues with autoconfigured TLS
==============================

These issues will manifest as an error in ``ironic-conductor`` logs looking
similar to (lines are wrapped for readability)::

    ERROR ironic.drivers.modules.agent_client [-]
    Failed to connect to the agent running on node d7c322f0-0354-4008-92b4-f49fb2201001
    for invoking command clean.get_clean_steps. Error:
    HTTPSConnectionPool(host='192.168.123.126', port=9999): Max retries exceeded with url:
    /v1/commands/?wait=true&agent_token=<token> (Caused by
    SSLError(SSLError(1, '[SSL: CERTIFICATE_VERIFY_FAILED] certificate verify failed (_ssl.c:897)'),)):
    requests.exceptions.SSLError: HTTPSConnectionPool(host='192.168.123.126', port=9999):
    Max retries exceeded with url: /v1/commands/?wait=true&agent_token=<token>
    (Caused by SSLError(SSLError(1, '[SSL: CERTIFICATE_VERIFY_FAILED] certificate verify failed (_ssl.c:897)'),))

The cause of the issue is that the Bare Metal service cannot access the ramdisk
with the TLS certificate provided by the ramdisk on first heartbeat. You can
inspect the stored certificate in ``/var/lib/ironic/certificates/<node>.crt``.

You can try connecting to the ramdisk using the IP address in the log message::

    curl -vL https://<IP address>:9999/v1/commands \
        --cacert /var/lib/ironic/certificates/<node UUID>.crt

You can get the detailed information about the certificate using openSSL::

    openssl x509 -text -noout -in /var/lib/ironic/certificates/<node UUID>.crt

Clock skew
----------

One possible source of the problem is a discrepancy between the hardware
clock on the node and the time on the machine with the Bare Metal service.
It can be detected by comparing the ``Not Before`` field in the ``openssl``
output with the timestamp of a log message.

The recommended solution is to enable the NTP support in ironic-python-agent by
passing the ``ipa-ntp-server`` argument with an address of an NTP server
reachable by the node.

If it is not possible, you need to ensure the correct hardware time on the
machine. Keep in mind a potential issue with timezones: an ability to store
timezone in hardware is pretty recent and may not be available. Since
ironic-python-agent is likely operating in UTC, the hardware clock should also
be set in UTC.

.. note::
   Microsoft Windows uses local time by default, so a machine that has
   previously run Windows will likely have wrong time.

I changed ironic.conf, and now I can't edit my nodes.
=====================================================

Whenever a node is created in ironic, default interfaces are identified
as part of driver composition. This maybe sourced from explicit default
values which have been set in ``ironic.conf`` or by the interface order
for the enabled interfaces list. The result of this is that the
``ironic-conductor`` cannot spawn a ``task`` using the composed driver,
as a portion of the driver is no longer enabled. This makes it difficult
to edit or update the node if the settings have been changed.

For example, with networking interfaces, if you have
``default_network_interface=neutron`` or
``enabled_network_interfaces=neutron,flat``
in your ``ironic.conf``, nodes would have been created with the ``neutron``
network interface.

This is because ``default_network_interface`` overrides the setting
for new nodes, and that setting is **saved** to the database nodes table.

Similarly, the order of ``enabled_network_interfaces`` takes priority, and
the first entry in the list is generally set to the default for the node upon
creation, and that record is **saved** to the database nodes table.

The only case where driver composition does *not* calculate a default is if
an explicit value is provided upon the creation of the node.

Example failure
---------------

A node in this state, when the ``network_interface`` was saved as ``neutron``,
yet the ``neutron`` interface is no longer enabled will fail basic state
transition requests:

.. code-block:: console

  $ baremetal node manage 7164efca-37ab-1213-1112-b731cf795a5a
  Could not find the following interface in the 'ironic.hardware.interfaces.network' entrypoint: neutron. Valid interfaces are ['flat']. (HTTP 400)

How to fix this?
----------------

Revert the changes you made to ``ironic.conf``.

This applies to any changes to any ``default_*_interface`` options or the
order of interfaces in the for the ``enabled_*_interfaces`` options.

Once the conductor has been restarted with the updated configuration, you
should now be able to update the interface using the ``baremetal node set``
command. In this example we use the ``network_interface`` as this is most
commonly where it is encountered:

.. code-block:: console

  $ baremetal node set $NAME_OR_UUID --network-interface flat

.. note:: There are additional paths one can take to remedy this sort of
   issue, however we encourage operators to be mindful of operational
   consistency when making major configuration changes.

Once you have updated the saved interfaces, you should be able to safely
return the ``ironic.conf`` configuration change in changing what interfaces
are enabled by the conductor.

I'm getting Out of Memory errors
================================

This issue, also known as the "the OOMKiller got my conductor" case,
is where your OS system memory reaches a point where the operating
system engages measures to shed active memory consumption in order
to prevent a complete failure of the machine. Unfortunately this
can cause unpredictable behavior.

How did I get here?
-------------------

One of the major consumers of memory in a host running an ironic-conductor is
transformation of disk images using the ``qemu-img`` tool. This tool, because
the disk images it works with are both compressed and out of linear block
order, requires a considerable amount of memory to efficently re-assemble
and write-out a disk to a device, or to simply convert the format such as
to a ``raw`` image.

By default, ironic's configuration limits this conversion to 1 GB of RAM
for the process, but each conversion does cause additional buffer memory
to be used, which increases overall system memory pressure. Generally
memory pressure alone from buffers will not cause an out of memory condition,
but the multiple conversions or deployments running at the same time
CAN cause extreme memory pressure and risk the system running out of memory.

How do I resolve this?
----------------------

This can be addressed a few different ways:

* Use raw images, however these images can be substantially larger
  and require more data to be transmitted "over the wire".
* Add more physical memory.
* Add swap space.
* Reduce concurrency, possibly via another conductor or changing the
  nova-compute.conf ``max_concurrent_builds`` parameter.
* Or finally, adjust the ``[DEFAULT]minimum_required_memory`` parameter
  in your ironic.conf file. The default should be considered a "default
  of last resort" and you may need to reserve additional memory. You may
  also wish to adjust the ``[DEFAULT]minimum_memory_wait_retries`` and
  ``[DEFAULT]minimum_memory_wait_time`` parameters.

Why does API return "Node is locked by host"?
=============================================

This error usually manifests as HTTP error 409 on the client side:

    Node d7e2aed8-50a9-4427-baaa-f8f595e2ceb3 is locked by host 192.168.122.1,
    please retry after the current operation is completed.

It happens, because an operation that modifies a node is requested, while
another such operation is running. The conflicting operation may be user
requested (e.g. a provisioning action) or related to the internal processes
(e.g. changing power state during :doc:`power-sync`). The reported host name
corresponds to the conductor instance that holds the lock.

Normally, these errors are transient and safe to retry after a few seconds. If
the lock is held for significant time, these are the steps you can take.

First of all, check the current ``provision_state`` of the node:

``verifying``
    means that the conductor is trying to access the node's BMC.
    If it happens for minutes, it means that the BMC is either unreachable or
    misbehaving. Double-check the information in ``driver_info``, especially
    the BMC address and credentials.

    If the access details seem correct, try resetting the BMC using, for
    example, its web UI.

``deploying``/``inspecting``/``cleaning``
    means that the conductor is doing some active work. It may include
    downloading or converting images, executing synchronous out-of-band deploy
    or clean steps, etc. A node can stay in this state for minutes, depending
    on various factors. Consult the conductor logs.

``available``/``manageable``/``wait call-back``/``clean wait``
    means that some background process is holding the lock. Most commonly it's
    the power synchronization loop. Similarly to the ``verifying`` state,
    it may mean that the BMC access is broken or too slow. The conductor logs
    will provide you insights on what is happening.

To trace the process using conductor logs:

#. Isolate the relevant log parts. Lock messages come from the
   ``ironic.conductor.task_manager`` module. You can also check the
   ``ironic.common.states`` module for any state transitions:

   .. code-block:: console

    $ grep -E '(ironic.conductor.task_manager|ironic.common.states|NodeLocked)' \
        conductor.log > state.log

#. Find the first instance of ``NodeLocked``. It may look like this (stripping
   timestamps and request IDs here and below for readability)::

    DEBUG ironic.conductor.task_manager [-] Attempting to get exclusive lock on node d7e2aed8-50a9-4427-baaa-f8f595e2ceb3 (for node update) __init__ /usr/lib/python3.6/site-packages/ironic/conductor/task_manager.py:233
    DEBUG ironic_lib.json_rpc.server [-] RPC error NodeLocked: Node d7e2aed8-50a9-4427-baaa-f8f595e2ceb3 is locked by host 192.168.57.53, please retry after the current operation is completed. _handle_error /usr/lib/python3.6/site-packages/ironic_lib/json_rpc/server.py:179

   The events right before this failure will provide you a clue on why the lock
   is held.

#. Find the last successful **exclusive** locking event before the failure, for
   example::

    DEBUG ironic.conductor.task_manager [-] Attempting to get exclusive lock on node d7e2aed8-50a9-4427-baaa-f8f595e2ceb3 (for provision action manage) __init__ /usr/lib/python3.6/site-packages/ironic/conductor/task_manager.py:233
    DEBUG ironic.conductor.task_manager [-] Node d7e2aed8-50a9-4427-baaa-f8f595e2ceb3 successfully reserved for provision action manage (took 0.01 seconds) reserve_node /usr/lib/python3.6/site-packages/ironic/conductor/task_manager.py:350
    DEBUG ironic.common.states [-] Exiting old state 'enroll' in response to event 'manage' on_exit /usr/lib/python3.6/site-packages/ironic/common/states.py:307
    DEBUG ironic.common.states [-] Entering new state 'verifying' in response to event 'manage' on_enter /usr/lib/python3.6/site-packages/ironic/common/states.py:313

   This is your root cause, the lock is held because of the BMC credentials
   verification.

#. Find when the lock is released (if at all). The messages look like this::

    DEBUG ironic.conductor.task_manager [-] Successfully released exclusive lock for provision action manage on node d7e2aed8-50a9-4427-baaa-f8f595e2ceb3 (lock was held 60.02 sec) release_resources /usr/lib/python3.6/site-packages/ironic/conductor/task_manager.py:447

   The message tells you the reason the lock was held (``for provision action
   manage``) and the amount of time it was held (60.02 seconds, which is way
   too much for accessing a BMC).

Unfortunately, due to the way the conductor is designed, it is not possible to
gracefully break a stuck lock held in ``*-ing`` states. As the last resort, you
may need to restart the affected conductor. See `Why are my nodes stuck in a
"-ing" state?`_.
