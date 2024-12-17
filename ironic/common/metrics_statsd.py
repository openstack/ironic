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

import contextlib
import logging
import socket

from oslo_config import cfg

from ironic.common import metrics

LOG = logging.getLogger(__name__)


CONF = cfg.CONF


class StatsdMetricLogger(metrics.MetricLogger):
    """Metric logger that reports data via the statsd protocol."""

    GAUGE_TYPE = 'g'
    COUNTER_TYPE = 'c'
    TIMER_TYPE = 'ms'

    def __init__(self, prefix, delimiter='.', host=None, port=None):
        """Initialize a StatsdMetricLogger

        The logger uses the given prefix list, delimiter, host, and port.

        :param prefix: Prefix for this metric logger.
        :param delimiter: Delimiter used to generate the full metric name.
        :param host: The statsd host
        :param port: The statsd port
        """
        super(StatsdMetricLogger, self).__init__(prefix,
                                                 delimiter=delimiter)

        self._host = host or CONF.metrics_statsd.statsd_host
        self._port = port or CONF.metrics_statsd.statsd_port

        self._target = (self._host, self._port)

    def _send(self, name, value, metric_type, sample_rate=None):
        """Send metrics to the statsd backend

        :param name: Metric name
        :param value: Metric value
        :param metric_type: Metric type (GAUGE_TYPE, COUNTER_TYPE,
            or TIMER_TYPE)
        :param sample_rate: Probabilistic rate at which the values will be sent
        """
        if sample_rate is None:
            metric = '%s:%s|%s' % (name, value, metric_type)
        else:
            metric = '%s:%s|%s@%s' % (name, value, metric_type, sample_rate)

        # Ideally, we'd cache a sending socket in self, but that
        # results in a socket getting shared by multiple green threads.
        with contextlib.closing(self._open_socket()) as sock:
            try:
                sock.settimeout(0.0)
                sock.sendto(metric.encode(), self._target)
            except socket.error as e:
                LOG.warning("Failed to send the metric value to host "
                            "%(host)s, port %(port)s. Error: %(error)s",
                            {'host': self._host, 'port': self._port,
                             'error': e})

    def _open_socket(self):
        return socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

    def _gauge(self, name, value):
        return self._send(name, value, self.GAUGE_TYPE)

    def _counter(self, name, value, sample_rate=None):
        return self._send(name, value, self.COUNTER_TYPE,
                          sample_rate=sample_rate)

    def _timer(self, name, value):
        return self._send(name, value, self.TIMER_TYPE)
