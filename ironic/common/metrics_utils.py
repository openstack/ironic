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

from oslo_config import cfg

from ironic.common import exception
from ironic.common.i18n import _
from ironic.common import metrics
from ironic.common import metrics_collector
from ironic.common import metrics_statsd


CONF = cfg.CONF


def get_metrics_logger(prefix='', backend=None, host=None, delimiter='.'):
    """Return a metric logger with the specified prefix.

    The format of the prefix is:
    [global_prefix<delim>][host_name<delim>]prefix
    where <delim> is the delimiter (default is '.')

    :param prefix: Prefix for this metric logger.
        Value should be a string or None.
    :param backend: Backend to use for the metrics system.
        Possible values are 'noop' and 'statsd'.
    :param host: Name of this node.
    :param delimiter: Delimiter to use for the metrics name.
    :return: The new MetricLogger.
    """
    if not isinstance(prefix, str):
        msg = (_("This metric prefix (%s) is of unsupported type. "
                 "Value should be a string or None")
               % str(prefix))
        raise exception.InvalidMetricConfig(msg)

    if CONF.metrics.prepend_host and host:
        if CONF.metrics.prepend_host_reverse:
            host = '.'.join(reversed(host.split('.')))

        if prefix:
            prefix = delimiter.join([host, prefix])
        else:
            prefix = host

    if CONF.metrics.global_prefix:
        if prefix:
            prefix = delimiter.join([CONF.metrics.global_prefix, prefix])
        else:
            prefix = CONF.metrics.global_prefix

    backend = backend or CONF.metrics.backend
    if backend == 'statsd':
        return metrics_statsd.StatsdMetricLogger(prefix, delimiter=delimiter)
    elif backend == 'noop':
        return metrics.NoopMetricLogger(prefix, delimiter=delimiter)
    elif backend == 'collector':
        return metrics_collector.DictCollectionMetricLogger(
            prefix, delimiter=delimiter)
    else:
        msg = (_("The backend is set to an unsupported type: "
                 "%s. Value should be 'noop' or 'statsd'.")
               % backend)
        raise exception.InvalidMetricConfig(msg)
