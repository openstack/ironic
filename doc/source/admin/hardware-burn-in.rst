.. _hardware-burn-in:

================
Hardware Burn-in
================

Overview
========

Workflows to onboard new hardware often include a stress-testing step to
provoke early failures and to avoid that these load-triggered issues only
occur when the nodes have already moved to production. These ``burn-in``
tests typically include CPU, memory, disk, and network. With the Xena
release, Ironic supports such tests as part of the cleaning framework.

The burn-in steps rely on standard tools such as
`stress-ng <https://wiki.ubuntu.com/Kernel/Reference/stress-ng>`_ for CPU
and memory, or `fio <https://fio.readthedocs.io/en/latest/>`_ for disk and
network. The burn-in cleaning steps are part of the generic hardware manager
in the Ironic Python Agent (IPA) and therefore the agent ramdisk does not
need to be bundled with a specific
:ironic-python-agent-doc:`IPA hardware manager
<admin/hardware_managers.html>` to have them available.

Each burn-in step accepts (or in the case of network: needs) some basic
configuration options, mostly to limit the duration of the test and to
specify the amount of resources to be used. The options are set on a node's
``driver-info`` and prefixed with ``agent_burnin_``. The options available
for the individual tests will be outlined below.

CPU burn-in
===========

The options, following a `agent_burnin_` + stress-ng stressor (`cpu`) +
stress-ng option schema, are:

* ``agent_burnin_cpu_timeout`` (default: 24 hours)
* ``agent_burnin_cpu_cpu`` (default: 0, meaning all CPUs)

to limit the overall runtime and to pick the number of CPUs to stress.

For instance, in order to limit the time of the CPU burn-in to 10 minutes
do:

.. code-block:: console

    baremetal node set --driver-info agent_burnin_cpu_timeout=600 \
        $NODE_NAME_OR_UUID

Then launch the test with:

.. code-block:: console

   baremetal node clean --clean-steps '[{"step": "burnin_cpu", \
       "interface": "deploy"}]' $NODE_NAME_OR_UUID

Memory burn-in
==============

The options, following a `agent_burnin_` + stress-ng stressor (`vm`) +
stress-ng option schema, are:

* ``agent_burnin_vm_timeout`` (default: 24 hours)
* ``agent_burnin_vm_vm-bytes`` (default: 98%)

to limit the overall runtime and to set the fraction of RAM to stress.

For instance, in order to limit the time of the memory burn-in to 1 hour
and the amount of RAM to be used to 75% run:

.. code-block:: console

    baremetal node set --driver-info agent_burnin_vm_timeout=3600 \
        $NODE_NAME_OR_UUID
    baremetal node set --driver-info agent_burnin_vm_vm-bytes=75 \
        $NODE_NAME_OR_UUID

Then launch the test with:

.. code-block:: console

   baremetal node clean --clean-steps '[{"step": "burnin_vm", \
       "interface": "deploy"}]' $NODE_NAME_OR_UUID

Disk burn-in
============

The options, following a `agent_burnin_` + fio stressor (`fio_disk`) +
fio option schema, are:

* agent_burnin_fio_disk_runtime (default: 0, meaning no time limit)
* agent_burnin_fio_disk_loops (default: 4)

to set the time limit and the number of iterations when going
over the disks.

For instance, in order to limit the number of loops to 2 set:

.. code-block:: console

    baremetal node set --driver-info agent_burnin_fio_disk_loops=2 \
        $NODE_NAME_OR_UUID

Then launch the test with:

.. code-block:: console

    baremetal node clean --clean-steps '[{"step": "burnin_disk", \
        "interface": "deploy"}]' $NODE_NAME_OR_UUID


Network burn-in
===============

Burning in the network needs a little more config, since we need a pair
of nodes to perform the test. Therefore, this test needs to set
``agent_burnin_fio_network_config`` JSON which requires a ``role`` field
(values: ``reader``, ``writer``) and a ``partner`` field (value is the
hostname of the other node to test), like:

.. code-block:: console

    baremetal node set --driver-info agent_burnin_fio_network_config= \
        '{"role": "writer", "partner": "$HOST2"}' $NODE_NAME_OR_UUID1
    baremetal node set --driver-info agent_burnin_fio_network_config= \
        '{"role": "reader", "partner": "$HOST1"}' $NODE_NAME_OR_UUID2

In addition and similar to the other tests, there is a runtime option
to be set (only on the writer):

.. code-block:: console

    baremetal node set --driver-info agent_burnin_fio_network_runtime=600 \
        $NODE_NAME_OR_UUID

Then launch the test with:

.. code-block:: console

    baremetal node clean --clean-steps '[{"step": "burnin_network",\
        "interface": "deploy"}]' $NODE_NAME_OR_UUID1
    baremetal node clean --clean-steps '[{"step": "burnin_network",\
        "interface": "deploy"}]' $NODE_NAME_OR_UUID2

Both nodes will wait for the other node to show up and block while waiting.
If the partner does not show up, the cleaning timeout will step in.

Additional Information
======================

All tests can be aborted at any moment with

.. code-block:: console

    baremetal node abort $NODE_NAME_OR_UUID

One can also launch multiple tests which will be run in sequence, e.g.:

.. code-block:: console

     baremetal node clean --clean-steps '[{"step": "burnin_cpu",\
        "interface": "deploy"}, {"step": "burnin_memory",\
        "interface": "deploy"}]' $NODE_NAME_OR_UUID

If desired, configuring ``fast-track`` may be helpful here as it allows
to keep the node up between consecutive calls of ``baremetal node clean``.
