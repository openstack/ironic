=====================
Ironic tempest plugin
=====================

This directory contains Tempest tests to cover the Ironic project,
as well as a plugin to automatically load these tests into tempest.

See the tempest plugin docs for information on using it:
http://docs.openstack.org/developer/tempest/plugin.html#using-plugins

To run all tests from this plugin, install ironic into your environment
and run::

    $ tox -e all-plugin -- ironic

To run a single test case, run with the test case name, for example::

    $ tox -e all-plugin -- ironic_tempest_plugin.tests.scenario.test_baremetal_basic_ops.BaremetalBasicOps.test_baremetal_server_ops

To run all tempest tests including this plugin, run::

    $ tox -e all-plugin
