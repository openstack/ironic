# Copyright 2026 The OpenStack Foundation.
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

from ironic.db.sqlalchemy import models
from ironic.tests import base


class TestTruncatedText(base.TestCase):

    def setUp(self):
        super(TestTruncatedText, self).setUp()
        self.db_type = models.TruncatedText()

    def test_process_bind_param_none(self):
        result = self.db_type.process_bind_param(None, None)
        self.assertIsNone(result)

    def test_process_bind_param_short_string(self):
        short_text = "This is a short event."
        result = self.db_type.process_bind_param(short_text, None)
        self.assertEqual(short_text, result)

    def test_process_bind_param_long_string(self):
        # Create a string larger than the constant limit
        long_text = "A" * (models.MAX_EVENT_BYTES + 5000)

        result = self.db_type.process_bind_param(long_text, None)

        self.assertLessEqual(
            len(result.encode('utf-8')), models.MAX_EVENT_BYTES)
        self.assertIn(models.TRUNCATE_MARKER, result)
        self.assertTrue(result.startswith("AAAA"))
        self.assertTrue(result.endswith("AAAA"))
