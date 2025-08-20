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

from unittest import mock


from ironic.common import metrics_collector
from ironic.tests import base


def connect(family=None, type=None, proto=None):
    """Dummy function to provide signature for autospec"""
    pass


class TestDictCollectionMetricLogger(base.TestCase):
    def setUp(self):
        super(TestDictCollectionMetricLogger, self).setUp()
        self.ml = metrics_collector.DictCollectionMetricLogger(
            'prefix', '.')

    @mock.patch('ironic.common.metrics_collector.'
                'DictCollectionMetricLogger._send',
                autospec=True)
    def test_gauge(self, mock_send):
        self.ml._gauge('metric', 10)
        mock_send.assert_called_once_with(self.ml, 'metric', 10, 'g')

    @mock.patch('ironic.common.metrics_collector.'
                'DictCollectionMetricLogger._send',
                autospec=True)
    def test_counter(self, mock_send):
        self.ml._counter('metric', 10)
        mock_send.assert_called_once_with(self.ml, 'metric', 10, 'c',
                                          sample_rate=None)

    @mock.patch('ironic.common.metrics_collector.'
                'DictCollectionMetricLogger._send',
                autospec=True)
    def test_timer(self, mock_send):
        self.ml._timer('metric', 10)
        mock_send.assert_called_once_with(self.ml, 'metric', 10, 'ms')

    def test_send(self):
        expected = {
            'part1.part1': {'count': 2, 'type': 'counter'},
            'part1.part2': {'type': 'gauge', 'value': 66},
            'part1.magic': {'count': 2, 'sum': 22, 'type': 'timer'},
        }
        self.ml._send('part1.part1', 1, 'c')
        self.ml._send('part1.part1', 1, 'c')
        self.ml._send('part1.part2', 66, 'g')
        self.ml._send('part1.magic', 2, 'ms')
        self.ml._send('part1.magic', 20, 'ms')
        results = self.ml.get_metrics_data()
        self.assertEqual(expected, results)
