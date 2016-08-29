#    Copyright (c) 2015 IBM, Corp.
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

import six

from ironic.common import exception
from ironic.tests import base


class TestIronicException(base.TestCase):
    def test____init__(self):
        expected = b'\xc3\xa9\xe0\xaf\xb2\xe0\xbe\x84'
        if six.PY3:
            expected = expected.decode('utf-8')
        message = six.unichr(233) + six.unichr(0x0bf2) + six.unichr(3972)
        exc = exception.IronicException(message)
        self.assertEqual(expected, exc.__str__())
