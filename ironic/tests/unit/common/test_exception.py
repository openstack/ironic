# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#    http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or
# implied.
# See the License for the specific language governing permissions and
# limitations under the License.


import re
from unittest import mock

from oslo_config import cfg

from ironic.common import exception
from ironic.tests import base

CONF = cfg.CONF


class Unserializable(object):
    def __str__(self):
        raise NotImplementedError('nostr')


class TestException(exception.IronicException):
    _msg_fmt = 'Some exception: %(spam)s, %(ham)s'


class TestIronicException(base.TestCase):
    def test___init___json_serializable(self):
        exc = TestException(spam=[1, 2, 3], ham='eggs')
        self.assertIn('[1, 2, 3]', str(exc))
        self.assertEqual('[1, 2, 3]', exc.kwargs['spam'])

    def test___init___string_serializable(self):
        exc = TestException(
            spam=type('ni', (object,), dict(a=1, b=2))(), ham='eggs'
        )
        check_str = 'ni object at'
        self.assertIn(check_str, str(exc))
        self.assertIn(check_str, exc.kwargs['spam'])

    @mock.patch.object(exception.LOG, 'error', autospec=True)
    def test___init___invalid_kwarg(self, log_mock):
        CONF.set_override('fatal_exception_format_errors', False,
                          group='errors')
        e = TestException(spam=Unserializable(), ham='eggs')
        message = \
            log_mock.call_args_list[0][0][0] % log_mock.call_args_list[0][0][1]
        self.assertIsNotNone(
            re.search('spam: .*JSON.* NotImplementedError: nostr', message),
            message
        )
        self.assertEqual({'ham': '"eggs"', 'code': 500}, e.kwargs)

    @mock.patch.object(exception.LOG, 'error', autospec=True)
    def test___init___invalid_kwarg_reraise(self, log_mock):
        CONF.set_override('fatal_exception_format_errors', True,
                          group='errors')
        self.assertRaises(KeyError, TestException, spam=Unserializable(),
                          ham='eggs')
        message = \
            log_mock.call_args_list[0][0][0] % log_mock.call_args_list[0][0][1]
        self.assertIsNotNone(
            re.search('spam: .*JSON.* NotImplementedError: nostr', message),
            message
        )
