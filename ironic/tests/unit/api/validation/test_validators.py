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

from unittest import mock

from ironic.api import validation
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


class TestResponseBodyValidation(test_base.TestCase):

    def setUp(self):
        super().setUp()

        self.schema = {
            'type': 'object',
            'properties': {'foo': {'type': 'string'}},
            'required': ['foo'],
        }

    @mock.patch.object(validation, 'LOG', autospec=True)
    def test_response_validation__error(self, mock_log):
        self.config(response_validation='error', group='api')

        @validation.response_body_schema(self.schema)
        def test_func():
            return {'foo': 123}

        self.assertRaises(exception.InvalidParameterValue, test_func)
        mock_log.exception.assert_not_called()

    @mock.patch.object(validation, 'LOG', autospec=True)
    def test_response_validation__warn(self, mock_log):
        self.config(response_validation='warn', group='api')

        @validation.response_body_schema(self.schema)
        def test_func():
            return {'foo': 123}

        result = test_func()
        self.assertEqual({'foo': 123}, result)
        mock_log.exception.assert_called_once_with('Schema failed to validate')

    @mock.patch.object(validation, 'LOG', autospec=True)
    def test_response_validation__ignore(self, mock_log):
        self.config(response_validation='ignore', group='api')

        @validation.response_body_schema(self.schema)
        def test_func():
            return {'foo': 123}

        # Should not call validator at all in ignore mode
        result = test_func()
        self.assertEqual({'foo': 123}, result)
        mock_log.exception.assert_not_called()
