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


from oslo_concurrency import lockutils
from oslo_config import cfg

from ironic.common import metrics


CONF = cfg.CONF

STATISTIC_DATA = {}


class DictCollectionMetricLogger(metrics.MetricLogger):
    """Metric logger that collects internal counters."""

    # These are internal typing labels in Ironic-lib.
    GAUGE_TYPE = 'g'
    COUNTER_TYPE = 'c'
    TIMER_TYPE = 'ms'

    def __init__(self, prefix, delimiter='.'):
        """Initialize the Collection Metrics Logger.

        The logger stores metrics data in a dictionary which can then be
        retrieved by the program utilizing it whenever needed utilizing a
        get_metrics_data call to return the metrics data structure.

        :param prefix: Prefix for this metric logger.
        :param delimiter: Delimiter used to generate the full metric name.
        """
        super(DictCollectionMetricLogger, self).__init__(
            prefix, delimiter=delimiter)

    @lockutils.synchronized('statistics-update')
    def _send(self, name, value, metric_type, sample_rate=None):
        """Send the metrics to be stored in memory.

        This memory updates the internal dictionary to facilitate
        collection of statistics, and the retrieval of them for
        consumers or plugins in Ironic to retrieve the statistic
        data utilizing the `get_metrics_data` method.

        :param name: Metric name
        :param value: Metric value
        :param metric_type: Metric type (GAUGE_TYPE, COUNTER_TYPE),
            TIMER_TYPE is not supported.
        :param sample_rate: Not Applicable.
        """

        global STATISTIC_DATA
        if metric_type == self.TIMER_TYPE:
            if name in STATISTIC_DATA:
                STATISTIC_DATA[name] = {
                    'count': STATISTIC_DATA[name]['count'] + 1,
                    'sum': STATISTIC_DATA[name]['sum'] + value,
                    'type': 'timer'
                }
            else:
                # Set initial data value.
                STATISTIC_DATA[name] = {
                    'count': 1,
                    'sum': value,
                    'type': 'timer'
                }
        elif metric_type == self.GAUGE_TYPE:
            STATISTIC_DATA[name] = {
                'value': value,
                'type': 'gauge'
            }
        elif metric_type == self.COUNTER_TYPE:
            if name in STATISTIC_DATA:
                # NOTE(TheJulia): Value is hard coded for counter
                # data types as a value of 1.
                STATISTIC_DATA[name] = {
                    'count': STATISTIC_DATA[name]['count'] + 1,
                    'type': 'counter'
                }
            else:
                STATISTIC_DATA[name] = {
                    'count': 1,
                    'type': 'counter'
                }

    def _gauge(self, name, value):
        return self._send(name, value, self.GAUGE_TYPE)

    def _counter(self, name, value, sample_rate=None):
        return self._send(name, value, self.COUNTER_TYPE,
                          sample_rate=sample_rate)

    def _timer(self, name, value):
        return self._send(name, value, self.TIMER_TYPE)

    def get_metrics_data(self):
        """Return the metrics collection dictionary.

        :returns: Dictionary containing the keys and values of
                  data stored via the metrics collection hooks.
                  The values themselves are dictionaries which
                  contain a type field, indicating if the statistic
                  is a counter, gauge, or timer. A counter has a
                  `count` field, a gauge value has a `value` field,
                  and a 'timer' fiend las a 'count' and 'sum' fields.
                  The multiple fields for for a timer type allows
                  for additional statistics to be implied from the
                  data once collected and compared over time.
        """
        return STATISTIC_DATA
