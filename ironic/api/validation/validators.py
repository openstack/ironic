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
from oslo_utils import timeutils
from oslo_utils import uuidutils

from ironic.common import exception
from ironic.common.i18n import _


_FORMAT_CHECKER = jsonschema.FormatChecker()


@_FORMAT_CHECKER.checks('date-time')
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


@_FORMAT_CHECKER.checks('uuid')
def _validate_uuid_format(instance: object) -> bool:
    # format checks constrain to the relevant primitive type
    # https://github.com/OAI/OpenAPI-Specification/issues/3148
    if not isinstance(instance, str):
        return True

    return uuidutils.is_uuid_like(instance)


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
        try:
            self.validator = validator_cls(
                schema, format_checker=_FORMAT_CHECKER
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
