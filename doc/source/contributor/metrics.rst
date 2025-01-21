Metrics
=======

Ironic provides a pluggable metrics library as of the 2.0.0 release.
The metrics backend to be used is configured via ``CONF.metrics.backend``.
Not all backends support all metrics types or metric sources.

The typical usage of metrics is to initialize and cache a metrics logger,
using the ``get_metrics_logger()`` method in ``metrics_utils``, then
use that object to decorate functions or create context managers to gather
metrics. The general convention is to provide the name of the module as the
first argument to set it as the prefix, then set the actual metric name to the
method name. For example:

.. code-block:: python

  from ironic import metrics_utils

  METRICS = metrics_utils.get_metrics_logger(__name__)

  @METRICS.timer('my_simple_method')
  def my_simple_method(arg, matey):
      pass

  def my_complex_method(arg, matey):
      with METRICS.timer('complex_method_pt_1'):
          do_some_work()

      with METRICS.timer('complex_method_pt_2'):
          do_more_work()

There are three different kinds of metrics:
  - **Timers** measure how long the code in the decorated method or context
    manager takes to execute, and emits the value as a timer metric. These
    are useful for measuring performance of a given block of code.
  - **Counters** increment a counter each time a decorated method or context
    manager is executed. These are useful for counting the number of times a
    method is called, or the number of times an event occurs.
  - **Gauges** return the value of a decorated method as a metric. This is
    useful when you want to monitor the value returned by a method over time.

Additionally, metrics can be sent directly, rather than using a context
manager or decorator, when appropriate. When used in this way, we will
simply emit the value provided as the requested metric type. For example:

.. code-block:: python

  from ironic import metrics_utils

  METRICS = metrics_utils.get_metrics_logger(__name__)

  def my_node_failure_method(node):
      if node.failed:
          METRICS.send_counter(node.uuid, 1)

The provided statsd backend natively supports all three metric types. For more
information about how statsd changes behavior based on the metric type, see
`statsd metric types <https://github.com/etsy/statsd/blob/master/docs/metric_types.md>`_
