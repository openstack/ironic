.. _metrics:

=========================
Emitting Software Metrics
=========================

Beginning with the Newton (6.1.0) release, the ironic services support
emitting internal performance data to
`statsd <https://github.com/etsy/statsd>`_. This allows operators to graph
and understand performance bottlenecks in their system.

This guide assumes you have a statsd server setup. For information on using
and configuring statsd, please see the
`statsd <https://github.com/etsy/statsd>`_ README and documentation.

These performance measurements, herein referred to as "metrics", can be
emitted from the Bare Metal service, including ironic-api, ironic-conductor,
and ironic-python-agent. By default, none of the services will emit metrics.

It is important to stress that not only statsd is supported for metrics
collection and transmission. This is covered later on in our documentation.

Configuring the Bare Metal Service to Enable Metrics with Statsd
================================================================

Enabling metrics in ironic-api and ironic-conductor
---------------------------------------------------

The ironic-api and ironic-conductor services can be configured to emit metrics
to statsd by adding the following to the ironic configuration file, usually
located at ``/etc/ironic/ironic.conf``::

  [metrics]
  backend = statsd

If a statsd daemon is installed and configured on every host running an ironic
service, listening on the default UDP port (8125), no further configuration is
needed. If you are using a remote statsd server, you must also supply
connection information in the ironic configuration file::

  [metrics_statsd]
  # Point this at your environments' statsd host
  statsd_host = 192.0.2.1
  statsd_port = 8125


Enabling metrics in ironic-python-agent
---------------------------------------

The ironic-python-agent process receives its configuration in the response from
the initial lookup request to the ironic-api service. This means to configure
ironic-python-agent to emit metrics, you must enable the agent metrics backend
in your ironic configuration file on all ironic-conductor hosts::

  [metrics]
  agent_backend = statsd

In order to reliably emit metrics from the ironic-python-agent, you must
provide a statsd server that is reachable from both the configured provisioning
and cleaning networks. The agent statsd connection information is configured
in the ironic configuration file as well::

  [metrics_statsd]
  # Point this at a statsd host reachable from the provisioning and cleaning nets
  agent_statsd_host = 198.51.100.2
  agent_statsd_port = 8125

.. Note::
   Use of a different metrics backend with the agent is not presently
   supported.

Transmission to the Message Bus Notifier
========================================

Regardless if you're using Ceilometer,
`ironic-prometheus-exporter <https://docs.openstack.org/ironic-prometheus-exporter/latest/>`_,
or some scripting you wrote to consume the message bus notifications,
metrics data can be sent to the message bus notifier from the timer methods
*and* additional gauge counters by utilizing the ``[metrics]backend``
configuration option and setting it to ``collector``. When this is the case,
Information is cached locally and periodically sent along with the general sensor
data update to the messaging notifier, which can consumed off of the message bus,
or via notifier plugin (such as is done with ironic-prometheus-exporter).

.. NOTE::
   Transmission of timer data only works for the Conductor or ``single-process``
   Ironic service model. A separate webserver process presently does not have
   the capability of triggering the call to retrieve and transmit the data.

.. NOTE::
   This functionality requires ironic-lib version 5.4.0 to be installed.

Types of Metrics Emitted
========================

The Bare Metal service emits timing metrics for every API method, as well as
for most driver methods. These metrics measure how long a given method takes
to execute.

A deployer with metrics enabled should expect between 100 and 500 distinctly
named data points to be emitted from the Bare Metal service. This will
increase if the metrics.preserve_host option is set to true or if multiple
drivers are used in the Bare Metal deployment. This estimate may be used to
determine if a deployer needs to scale their metrics backend to handle the
additional load before enabling metrics. To see which metrics have changed names
or have been removed between releases, refer to the `ironic release notes
<https://docs.openstack.org/releasenotes/ironic/>`_.

Additional conductor metrics in the form of counts will also be generated in
limited locations where petinant to the activity of the conductor.

.. note::
  With the default statsd configuration, each timing metric may create
  additional metrics due to how statsd handles timing metrics. For more
  information, see statds documentation on
  `metric types <https://github.com/etsy/statsd/blob/master/docs/metric_types.md#timing>`_.

The ironic-python-agent ramdisk emits timing metrics for every API method.

Deployers who use custom HardwareManagers can emit custom metrics for their
hardware. For more information on custom HardwareManagers, and emitting
metrics from them, please see the
:ironic-python-agent-doc:`ironic-python-agent documentation <>`.


Adding New Metrics
==================

If you're a developer, and would like to add additional metrics to ironic,
please see the
:ironic-lib-doc:`ironic-lib developer documentation <>`
for details on how to use
the metrics library. A release note should also be created each time a metric
is changed or removed to alert deployers of the change.
