# Licensed under the Apache License, Version 2.0 (the "License"); you may
# not use this file except in compliance with the License. You may obtain
# a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
# WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
# License for the specific language governing permissions and limitations
# under the License.

from ironic.api.validation import validators
from ironic.common import exception
from ironic.tests import base as test_base


class TestSchemaValidator(test_base.TestCase):

    def test_uuid_format(self):
        schema = {'type': 'string', 'format': 'uuid'}
        validator = validators.SchemaValidator(schema)

        # passes
        validator.validate('d1903ad5-c774-4bfe-8cf4-8e08d8dbb4d3')

        # fails
        self.assertRaises(
            exception.InvalidParameterValue,
            validator.validate,
            'invalid uuid'
        )

    def test_datetime_format(self):
        schema = {'type': 'string', 'format': 'date-time'}
        validator = validators.SchemaValidator(schema)

        # passes
        validator.validate('2019-10-12T07:20:50.52Z')

        # fails
        self.assertRaises(
            exception.InvalidParameterValue,
            validator.validate,
            'invalid date-time'
        )
