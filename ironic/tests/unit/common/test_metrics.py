# Copyright 2016 Rackspace Hosting
# All Rights Reserved
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

import types
from unittest import mock

from oslo_utils import reflection

from ironic.common import metrics
from ironic.common import metrics_utils
from ironic.tests import base


METRICS = metrics_utils.get_metrics_logger(prefix='foo', backend='noop')


@METRICS.timer('testing1')
def timer_check(run, timer=None):
    pass


@METRICS.counter('testing2')
def counter_check(run, counter=None):
    pass


@METRICS.gauge('testing2')
def gauge_check(run, gauge=None):
    pass


class MockedMetricLogger(metrics.MetricLogger):
    _gauge = mock.Mock(spec_set=types.FunctionType)
    _counter = mock.Mock(spec_set=types.FunctionType)
    _timer = mock.Mock(spec_set=types.FunctionType)


class TestMetricReflection(base.TestCase):
    def test_timer_reflection(self):
        # Ensure our decorator is done correctly (functools.wraps) and we can
        # get the arguments of our decorated function.
        expected = ['run', 'timer']
        signature = reflection.get_signature(timer_check)
        parameters = list(signature.parameters)
        self.assertEqual(expected, parameters)

    def test_counter_reflection(self):
        # Ensure our decorator is done correctly (functools.wraps) and we can
        # get the arguments of our decorated function.
        expected = ['run', 'counter']
        signature = reflection.get_signature(counter_check)
        parameters = list(signature.parameters)
        self.assertEqual(expected, parameters)

    def test_gauge_reflection(self):
        # Ensure our decorator is done correctly (functools.wraps) and we can
        # get the arguments of our decorated function.
        expected = ['run', 'gauge']
        signature = reflection.get_signature(gauge_check)
        parameters = list(signature.parameters)
        self.assertEqual(expected, parameters)


class TestMetricLogger(base.TestCase):
    def setUp(self):
        super(TestMetricLogger, self).setUp()
        self.ml = MockedMetricLogger('prefix', '.')
        self.ml_no_prefix = MockedMetricLogger('', '.')
        self.ml_other_delim = MockedMetricLogger('prefix', '*')
        self.ml_default = MockedMetricLogger()

    def test_init(self):
        self.assertEqual(self.ml._prefix, 'prefix')
        self.assertEqual(self.ml._delimiter, '.')

        self.assertEqual(self.ml_no_prefix._prefix, '')
        self.assertEqual(self.ml_other_delim._delimiter, '*')
        self.assertEqual(self.ml_default._prefix, '')

    def test_get_metric_name(self):
        self.assertEqual(
            self.ml.get_metric_name('metric'),
            'prefix.metric')

        self.assertEqual(
            self.ml_no_prefix.get_metric_name('metric'),
            'metric')

        self.assertEqual(
            self.ml_other_delim.get_metric_name('metric'),
            'prefix*metric')

    def test_send_gauge(self):
        self.ml.send_gauge('prefix.metric', 10)
        self.ml._gauge.assert_called_once_with('prefix.metric', 10)

    def test_send_counter(self):
        self.ml.send_counter('prefix.metric', 10)
        self.ml._counter.assert_called_once_with(
            'prefix.metric', 10,
            sample_rate=None)
        self.ml._counter.reset_mock()

        self.ml.send_counter('prefix.metric', 10, sample_rate=1.0)
        self.ml._counter.assert_called_once_with(
            'prefix.metric', 10,
            sample_rate=1.0)
        self.ml._counter.reset_mock()

        self.ml.send_counter('prefix.metric', 10, sample_rate=0.0)
        self.assertFalse(self.ml._counter.called)

    def test_send_timer(self):
        self.ml.send_timer('prefix.metric', 10)
        self.ml._timer.assert_called_once_with('prefix.metric', 10)

    @mock.patch(
        'ironic.common.metrics._time', autospec=True)
    @mock.patch(
        'ironic.common.metrics.MetricLogger.send_timer',
        autospec=True)
    def test_decorator_timer(self, mock_timer, mock_time):
        mock_time.side_effect = [1, 43]

        @self.ml.timer('foo.bar.baz')
        def func(x):
            return x * x

        func(10)

        mock_timer.assert_called_once_with(self.ml, 'prefix.foo.bar.baz',
                                           42 * 1000)

    @mock.patch(
        'ironic.common.metrics.MetricLogger.send_counter',
        autospec=True)
    def test_decorator_counter(self, mock_counter):

        @self.ml.counter('foo.bar.baz')
        def func(x):
            return x * x

        func(10)

        mock_counter.assert_called_once_with(self.ml, 'prefix.foo.bar.baz', 1,
                                             sample_rate=None)

    @mock.patch(
        'ironic.common.metrics.MetricLogger.send_counter',
        autospec=True)
    def test_decorator_counter_sample_rate(self, mock_counter):

        @self.ml.counter('foo.bar.baz', sample_rate=0.5)
        def func(x):
            return x * x

        func(10)

        mock_counter.assert_called_once_with(self.ml, 'prefix.foo.bar.baz', 1,
                                             sample_rate=0.5)

    @mock.patch(
        'ironic.common.metrics.MetricLogger.send_gauge',
        autospec=True)
    def test_decorator_gauge(self, mock_gauge):
        @self.ml.gauge('foo.bar.baz')
        def func(x):
            return x

        func(10)

        mock_gauge.assert_called_once_with(self.ml, 'prefix.foo.bar.baz', 10)

    @mock.patch(
        'ironic.common.metrics._time', autospec=True)
    @mock.patch(
        'ironic.common.metrics.MetricLogger.send_timer',
        autospec=True)
    def test_context_mgr_timer(self, mock_timer, mock_time):
        mock_time.side_effect = [1, 43]

        with self.ml.timer('foo.bar.baz'):
            pass

        mock_timer.assert_called_once_with(self.ml, 'prefix.foo.bar.baz',
                                           42 * 1000)

    @mock.patch(
        'ironic.common.metrics.MetricLogger.send_counter',
        autospec=True)
    def test_context_mgr_counter(self, mock_counter):

        with self.ml.counter('foo.bar.baz'):
            pass

        mock_counter.assert_called_once_with(self.ml, 'prefix.foo.bar.baz', 1,
                                             sample_rate=None)

    @mock.patch(
        'ironic.common.metrics.MetricLogger.send_counter',
        autospec=True)
    def test_context_mgr_counter_sample_rate(self, mock_counter):

        with self.ml.counter('foo.bar.baz', sample_rate=0.5):
            pass

        mock_counter.assert_called_once_with(self.ml, 'prefix.foo.bar.baz', 1,
                                             sample_rate=0.5)
