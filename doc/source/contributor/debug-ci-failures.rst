.. _debug-ci-failures:

=====================
Debugging CI failures
=====================


If you see ``FAILURE`` in one or more jobs for your patch please don't panic.
This guide may help you to find the initial reason for the failure.
When clicking in the failed job you will be redirect to the Zuul web page that
contains all the information about the job build.


Zuul Web Page
=============

The page has three tabs: ``Summary``, ``Logs`` and ``Console``.

* Summary: Contains overall information about the build of the job, if the job
  build failed it will contain a general output of the failure.

* Logs:  Contains all configurations and log files about all services that
  were used in the job. This will give you an overall idea of the failures and
  you can identify services that may be involved. The ``job-output`` file can
  give an overall idea of the failures and what services may be involved.

* Console: Contains all the playbooks that were executed, by clicking in the
  arrow before each playbook name you can find the roles and commands that were
  executed.

Frequent Annoying Quirks (FAQ)
==============================

Networking (external/infra)
---------------------------

Ironic jobs, with more frequency than most, use external network resources
and are more susceptible to failures caused by temporary connectivity issues.

Known issues may include:

- Failures building IPA images in any job ending in -src or jobs running
  against ironic-python-agent-builder. We should ensure the outage is resolved
  by testing the URL locally before rechceking.
- Unexpected/unexplainable failures in multinode may be caused by failed
  connectivity between two deployed devstack nodes. Any failures in the CI
  donor cloud causing network issues between two separate devstack VMs under
  coordinated test will cause failures.

Networking (OpenStack)
----------------------

There are issues which can also cause networking failures to occur inside
the job directly.

Known issues may include:

- Some dnsmasq versions have an issue which causes them to crash or segfault
  during automatic reconfiguration. Certain errors in the neutron dhcp agent
  (q-dhcp service in devstack) indicate that dnsmasq errored and must be
  respawned. One quick way to rule this out is to search ``screen-q-dhcp.txt``
  for the string ``'dnsmasq', '--no-hosts'`` -- these spawn logs should only
  show up after an inability to find a PID file (Error: No such file or
  directory /opt/stack/data/neutron/UUID/pid). There should be no messages
  about respawning the process.
- EDK2 firmwares have known issues with IPv6, limiting our ability to test it.
