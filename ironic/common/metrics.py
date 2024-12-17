# Copyright 2016 Rackspace Hosting
# All Rights Reserved.
#
#    Licensed under the Apache License, Version 2.0 (the "License"); you may
#    not use this file except in compliance with the License. You may obtain
#    a copy of the License at
#
#         http://www.apache.org/licenses/LICENSE-2.0
#
#    Unless required by applicable law or agreed to in writing, software
#    distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
#    WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
#    License for the specific language governing permissions and limitations
#    under the License.

import abc
import functools
import random
import time

from ironic.common import exception
from ironic.common.i18n import _


class Timer(object):
    """A timer decorator and context manager.

    This metric type times the decorated method or code running inside the
    context manager, and emits the time as the metric value. It is bound to
    this MetricLogger.  For example::

      from ironic.common import metrics_utils

      METRICS = metrics_utils.get_metrics_logger()

      @METRICS.timer('foo')
      def foo(bar, baz):
          print bar, baz

      with METRICS.timer('foo'):
          do_something()
    """
    def __init__(self, metrics, name):
        """Init the decorator / context manager.

        :param metrics: The metric logger
        :param name: The metric name
        """
        if not isinstance(name, str):
            raise TypeError(_("The metric name is expected to be a string. "
                            "Value is %s") % name)
        self.metrics = metrics
        self.name = name
        self._start = None

    def __call__(self, f):
        @functools.wraps(f)
        def wrapped(*args, **kwargs):
            start = _time()
            result = f(*args, **kwargs)
            duration = _time() - start

            # Log the timing data (in ms)
            self.metrics.send_timer(self.metrics.get_metric_name(self.name),
                                    duration * 1000)
            return result
        return wrapped

    def __enter__(self):
        self._start = _time()

    def __exit__(self, exc_type, exc_val, exc_tb):
        duration = _time() - self._start
        # Log the timing data (in ms)
        self.metrics.send_timer(self.metrics.get_metric_name(self.name),
                                duration * 1000)


class Counter(object):
    """A counter decorator and context manager.

    This metric type increments a counter every time the decorated method or
    context manager is executed. It is bound to this MetricLogger. For
    example::

      from ironic.common import metrics_utils

      METRICS = metrics_utils.get_metrics_logger()

      @METRICS.counter('foo')
      def foo(bar, baz):
          print bar, baz

      with METRICS.counter('foo'):
          do_something()
    """
    def __init__(self, metrics, name, sample_rate):
        """Init the decorator / context manager.

        :param metrics: The metric logger
        :param name: The metric name
        :param sample_rate: Probabilistic rate at which the values will be sent
        """
        if not isinstance(name, str):
            raise TypeError(_("The metric name is expected to be a string. "
                            "Value is %s") % name)

        if (sample_rate is not None
                and (sample_rate < 0.0 or sample_rate > 1.0)):
            msg = _("sample_rate is set to %s. Value must be None "
                    "or in the interval [0.0, 1.0]") % sample_rate
            raise ValueError(msg)

        self.metrics = metrics
        self.name = name
        self.sample_rate = sample_rate

    def __call__(self, f):
        @functools.wraps(f)
        def wrapped(*args, **kwargs):
            self.metrics.send_counter(
                self.metrics.get_metric_name(self.name),
                1, sample_rate=self.sample_rate)

            result = f(*args, **kwargs)

            return result
        return wrapped

    def __enter__(self):
        self.metrics.send_counter(self.metrics.get_metric_name(self.name),
                                  1, sample_rate=self.sample_rate)

    def __exit__(self, exc_type, exc_val, exc_tb):
        pass


class Gauge(object):
    """A gauge decorator.

    This metric type returns the value of the decorated method as a metric
    every time the method is executed. It is bound to this MetricLogger. For
    example::

      from ironic.common import metrics_utils

      METRICS = metrics_utils.get_metrics_logger()

      @METRICS.gauge('foo')
      def add_foo(bar, baz):
          return (bar + baz)
    """
    def __init__(self, metrics, name):
        """Init the decorator / context manager.

        :param metrics: The metric logger
        :param name: The metric name
        """
        if not isinstance(name, str):
            raise TypeError(_("The metric name is expected to be a string. "
                            "Value is %s") % name)
        self.metrics = metrics
        self.name = name

    def __call__(self, f):
        @functools.wraps(f)
        def wrapped(*args, **kwargs):
            result = f(*args, **kwargs)
            self.metrics.send_gauge(self.metrics.get_metric_name(self.name),
                                    result)

            return result
        return wrapped


def _time():
    """Wraps time.time() for simpler testing."""
    return time.time()


class MetricLogger(object, metaclass=abc.ABCMeta):
    """Abstract class representing a metrics logger.

    A MetricLogger sends data to a backend (noop or statsd).
    The data can be a gauge, a counter, or a timer.

    The data sent to the backend is composed of:
      - a full metric name
      - a numeric value

    The format of the full metric name is:
        _prefix<delim>name
    where:
        - _prefix: [global_prefix<delim>][uuid<delim>][host_name<delim>]prefix
        - name: the name of this metric
        - <delim>: the delimiter. Default is '.'
    """

    def __init__(self, prefix='', delimiter='.'):
        """Init a MetricLogger.

        :param prefix: Prefix for this metric logger. This string will prefix
            all metric names.
        :param delimiter: Delimiter used to generate the full metric name.
        """
        self._prefix = prefix
        self._delimiter = delimiter

    def get_metric_name(self, name):
        """Get the full metric name.

        The format of the full metric name is:
           _prefix<delim>name
        where:
           - _prefix: [global_prefix<delim>][uuid<delim>][host_name<delim>]
             prefix
           - name: the name of this metric
           - <delim>: the delimiter. Default is '.'


        :param name: The metric name.
        :return: The full metric name, with logger prefix, as a string.
        """
        if not self._prefix:
            return name
        return self._delimiter.join([self._prefix, name])

    def send_gauge(self, name, value):
        """Send gauge metric data.

        Gauges are simple values.
        The backend will set the value of gauge 'name' to 'value'.

        :param name: Metric name
        :param value: Metric numeric value that will be sent to the backend
        """
        self._gauge(name, value)

    def send_counter(self, name, value, sample_rate=None):
        """Send counter metric data.

        Counters are used to count how many times an event occurred.
        The backend will increment the counter 'name' by the value 'value'.

        Optionally, specify sample_rate in the interval [0.0, 1.0] to
        sample data probabilistically where::

            P(send metric data) = sample_rate

        If sample_rate is None, then always send metric data, but do not
        have the backend send sample rate information (if supported).

        :param name: Metric name
        :param value: Metric numeric value that will be sent to the backend
        :param sample_rate: Probabilistic rate at which the values will be
            sent. Value must be None or in the interval [0.0, 1.0].
        """
        if (sample_rate is None or random.random() < sample_rate):
            return self._counter(name, value,
                                 sample_rate=sample_rate)

    def send_timer(self, name, value):
        """Send timer data.

        Timers are used to measure how long it took to do something.

        :param m_name: Metric name
        :param m_value: Metric numeric value that will be sent to the backend
        """
        self._timer(name, value)

    def timer(self, name):
        return Timer(self, name)

    def counter(self, name, sample_rate=None):
        return Counter(self, name, sample_rate)

    def gauge(self, name):
        return Gauge(self, name)

    @abc.abstractmethod
    def _gauge(self, name, value):
        """Abstract method for backends to implement gauge behavior."""

    @abc.abstractmethod
    def _counter(self, name, value, sample_rate=None):
        """Abstract method for backends to implement counter behavior."""

    @abc.abstractmethod
    def _timer(self, name, value):
        """Abstract method for backends to implement timer behavior."""

    def get_metrics_data(self):
        """Return the metrics collection, if available."""
        raise exception.MetricsNotSupported()


class NoopMetricLogger(MetricLogger):
    """Noop metric logger that throws away all metric data."""
    def _gauge(self, name, value):
        pass

    def _counter(self, name, value, sample_rate=None):
        pass

    def _timer(self, m_name, value):
        pass
