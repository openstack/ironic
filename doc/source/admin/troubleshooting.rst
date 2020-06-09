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

       openstack baremetal node list --provision-state available --no-maintenance --unassociated

   If this command does not show enough nodes, use generic ``openstack baremetal
   node list`` to check other nodes. For example, nodes in ``manageable`` state
   should be made available::

       openstack baremetal node provide <IRONIC NODE>

   The Bare metal service automatically puts a node in maintenance mode if
   there are issues with accessing its management interface. Check the power
   credentials (e.g. ``ipmi_address``, ``ipmi_username`` and ``ipmi_password``)
   and then move the node out of maintenance mode::

       openstack baremetal node maintenance unset <IRONIC NODE>

   The ``node validate`` command can be used to verify that all required fields
   are present. The following command should not return anything::

       openstack baremetal node validate <IRONIC NODE> | grep -E '(power|management)\W*False'

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

       openstack --os-baremetal-api-version 1.21 baremetal node list --fields uuid name resource_class

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
   requested resource class, the request will result in a "Nova valid host
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

        $ openstack baremetal node show <IRONIC NODE> --fields properties
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

        $ openstack baremetal node show <IRONIC NODE> --fields properties
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

   .. TODO(dtantsur): explain inspecting the placement API

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

  <node-uuid>[_<instance-uuid>]_<timestamp yyyy-mm-dd-hh:mm:ss>.tar.gz

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
sort of Input/Output operation.

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
  ``[DEFAULT]force_raw_images`` option, in particular with the ``iscsi``
  deployment interface. Users using glance and the ``direct`` deployment
  interface may also experience issues here as the conductor will cache
  the image to be written which takes place when the
  ``[agent]image_download_source`` is set to ``http`` instead of ``swift``.

* Write of a QCOW2 file over the ``iscsi`` deployment interface from the
  conductor to the node being deployed can result in large amounts of
  "white space" to be written to be transmitted over the wire and written
  to the end device.

.. note::
   The QCOW2 image conversion utility does consume quite a bit of memory
   when converting images or writing them to the end storage device. This
   is because the files are not sequential in nature, and must be re-assembled
   from an internal block mapping. Internally Ironic limits this to 1GB
   of RAM. Operators performing large numbers of deployments may wish to
   explore the ``direct`` deployment interface in these sorts of cases in
   order to minimize the conductor becoming a limiting factor due to memory
   and network IO.

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
