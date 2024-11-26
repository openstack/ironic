# Licensed under the Apache License, Version 2.0 (the "License"); you may
# not use this file except in compliance with the License. You may obtain
# a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
# WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
# License for the specific language governing permissions and limitations
# under the License.

"""Internal implementation of request/response validating middleware."""

import jsonschema
from jsonschema import exceptions as jsonschema_exc
from oslo_utils import timeutils
from oslo_utils import uuidutils

from ironic.common import exception
from ironic.common.i18n import _


@jsonschema.FormatChecker.cls_checks('date-time')
def _validate_datetime_format(instance: object) -> bool:
    # format checks constrain to the relevant primitive type
    # https://github.com/OAI/OpenAPI-Specification/issues/3148
    if not isinstance(instance, str):
        return True
    try:
        timeutils.parse_isotime(instance)
    except ValueError:
        return False
    else:
        return True


@jsonschema.FormatChecker.cls_checks('uuid')
def _validate_uuid_format(instance: object) -> bool:
    # format checks constrain to the relevant primitive type
    # https://github.com/OAI/OpenAPI-Specification/issues/3148
    if not isinstance(instance, str):
        return True

    return uuidutils.is_uuid_like(instance)


class FormatChecker(jsonschema.FormatChecker):
    """A FormatChecker can output the message from cause exception

    We need understandable validation errors messages for users. When a
    custom checker has an exception, the FormatChecker will output a
    readable message provided by the checker.
    """

    def check(self, param_value, format):
        """Check whether the param_value conforms to the given format.

        :param param_value: the param_value to check
        :type: any primitive type (str, number, bool)
        :param str format: the format that param_value should conform to
        :raises: :exc:`FormatError` if param_value does not conform to format
        """

        if format not in self.checkers:
            return

        # For safety reasons custom checkers can be registered with
        # allowed exception types. Anything else will fall into the
        # default formatter.
        func, raises = self.checkers[format]
        result, cause = None, None

        try:
            result = func(param_value)
        except raises as e:
            cause = e
        if not result:
            msg = '%r is not a %r' % (param_value, format)
            raise jsonschema_exc.FormatError(msg, cause=cause)


class SchemaValidator:
    """A validator class

    This class is changed from Draft202012Validator to add format checkers for
    data formats that are common in the Ironic API as well as add better error
    messages.
    """

    validator = None
    validator_org = jsonschema.Draft202012Validator

    def __init__(
        self, schema, is_body=True
    ):
        self.is_body = is_body
        validator_cls = jsonschema.validators.extend(self.validator_org)
        format_checker = FormatChecker()
        try:
            self.validator = validator_cls(
                schema, format_checker=format_checker
            )
        except Exception:
            raise

    def validate(self, *args, **kwargs):
        try:
            self.validator.validate(*args, **kwargs)
        except jsonschema.ValidationError as e:
            error_msg = _('Schema error: %s') % e.message
            # Sometimes the root message is too generic, try to find a possible
            # root cause:
            cause = None
            current = e
            while current.context:
                current = jsonschema.exceptions.best_match(current.context)
                cause = current.message
            if cause is not None:
                error_msg += _('. Possible root cause: %s') % cause
            raise exception.InvalidParameterValue(error_msg)
