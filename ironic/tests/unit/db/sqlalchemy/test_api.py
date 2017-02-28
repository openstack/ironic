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

import inspect

from ironic.db.sqlalchemy import api as sqlalchemy_api
from ironic.tests import base as test_base


class TestDBWriteMethodsRetryOnDeadlock(test_base.TestCase):

    def test_retry_on_deadlock(self):
        # This test ensures that every dbapi method doing database write is
        # wrapped with retry_on_deadlock decorator
        for name, method in inspect.getmembers(sqlalchemy_api.Connection,
                                               predicate=inspect.ismethod):
            src = inspect.getsource(method)
            if 'with _session_for_write()' in src:
                self.assertIn(
                    '@oslo_db_api.retry_on_deadlock', src,
                    'oslo_db\'s retry_on_deadlock decorator not '
                    'applied to method ironic.db.sqlalchemy.api.Connection.%s '
                    'doing database write' % name)
