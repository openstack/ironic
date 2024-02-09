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

import functools
import inspect

import jsonschema
from oslo_utils import netutils
from oslo_utils import strutils
from oslo_utils import uuidutils

from ironic.common import exception
from ironic.common.i18n import _
from ironic.common import utils


def string(name, value):
    """Validate that the value is a string

    :param name: Name of the argument
    :param value: A string value
    :returns: The string value, or None if value is None
    :raises: InvalidParameterValue if the value is not a string
    """
    if value is None:
        return
    if not isinstance(value, str):
        raise exception.InvalidParameterValue(
            _('Expected string for %s: %s') % (name, value))
    return value


def boolean(name, value):
    """Validate that the value is a string representing a boolean

    :param name: Name of the argument
    :param value: A string value
    :returns: The boolean representation of the value, or None if value is None
    :raises: InvalidParameterValue if the value cannot be converted to a
             boolean
    """
    if value is None:
        return
    try:
        return strutils.bool_from_string(value, strict=True)
    except ValueError as e:
        raise exception.InvalidParameterValue(
            _('Invalid %s: %s') % (name, e))


def uuid(name, value):
    """Validate that the value is a UUID

    :param name: Name of the argument
    :param value: A UUID string value
    :returns: The value, or None if value is None
    :raises: InvalidParameterValue if the value is not a valid UUID
    """
    if value is None:
        return
    if not uuidutils.is_uuid_like(value):
        raise exception.InvalidParameterValue(
            _('Expected UUID for %s: %s') % (name, value))
    return value


def name(name, value):
    """Validate that the value is a logical name

    :param name: Name of the argument
    :param value: A logical name string value
    :returns: The value, or None if value is None
    :raises: InvalidParameterValue if the value is not a valid logical name
    """
    if value is None:
        return
    if not utils.is_valid_logical_name(value):
        raise exception.InvalidParameterValue(
            _('Expected name for %s: %s') % (name, value))
    return value


def host_port(name, value):
    if value is None:
        return
    try:
        host, port = netutils.parse_host_port(value)
    except (ValueError, TypeError) as exc:
        raise exception.InvalidParameterValue(f'{name}: {exc}')
    if not host:
        raise exception.InvalidParameterValue(_('Missing host in %s') % name)
    return value


def uuid_or_name(name, value):
    """Validate that the value is a UUID or logical name

    :param name: Name of the argument
    :param value: A UUID or logical name string value
    :returns: The value, or None if value is None
    :raises: InvalidParameterValue if the value is not a valid UUID or
             logical name
    """
    if value is None:
        return
    if (not utils.is_valid_logical_name(value)
            and not uuidutils.is_uuid_like(value)):
        raise exception.InvalidParameterValue(
            _('Expected UUID or name for %s: %s') % (name, value))
    return value


def string_list(name, value):
    """Validate and convert comma delimited string to a list.

    :param name: Name of the argument
    :param value: A comma separated string of values
    :returns: A list of unique values (lower-cased), maintaining the
              same order, or None if value is None
    :raises: InvalidParameterValue if the value is not a string
    """
    value = string(name, value)
    if value is None:
        return
    items = []
    for v in str(value).split(','):
        v_norm = v.strip().lower()
        if v_norm and v_norm not in items:
            items.append(v_norm)
    return items


def integer(name, value):
    """Validate that the value represents an integer

    :param name: Name of the argument
    :param value: A value representing an integer
    :returns: The value as an int, or None if value is None
    :raises: InvalidParameterValue if the value does not represent an integer
    """
    if value is None:
        return
    try:
        return int(value)
    except (ValueError, TypeError):
        raise exception.InvalidParameterValue(
            _('Expected an integer for %s: %s') % (name, value))


def mac_address(name, value):
    """Validate that the value represents a MAC address

    :param name: Name of the argument
    :param value: A string value representing a MAC address
    :returns: The value as a normalized MAC address, or None if value is None
    :raises: InvalidParameterValue if the value is not a valid MAC address
    """
    if value is None:
        return
    try:
        return utils.validate_and_normalize_mac(value)
    except exception.InvalidMAC:
        raise exception.InvalidParameterValue(
            _('Expected valid MAC address for %s: %s') % (name, value))


def _or(name, value, validators):
    last_error = None
    for v in validators:
        try:
            return v(name=name, value=value)
        except exception.Invalid as e:
            last_error = e
    if last_error:
        raise last_error


def or_valid(*validators):
    """Validates if at least one supplied validator passes

    :param name: Name of the argument
    :param value: A value
    :returns: The value returned from the first successful validator
    :raises: The error from the last validator when
             every validation fails
    """
    assert validators, 'No validators specified for or_valid'
    return functools.partial(_or, validators=validators)


def _and(name, value, validators):
    for v in validators:
        value = v(name=name, value=value)
    return value


def and_valid(*validators):
    """Validates that every supplied validator passes

    The value returned from each validator is passed as the value to the next
    one.

    :param name: Name of the argument
    :param value: A value
    :returns: The value transformed through every supplied validator
    :raises: The error from the first failed validator
    """
    assert validators, 'No validators specified for or_valid'
    return functools.partial(_and, validators=validators)


def _validate_schema(name, value, schema):
    if value is None:
        return
    try:
        jsonschema.validate(value, schema)
    except jsonschema.exceptions.ValidationError as e:
        error_msg = _('Schema error for %s: %s') % (name, e.message)
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
    return value


def schema(schema):
    """Return a validator function which validates the value with jsonschema

    :param: schema dict representing jsonschema to validate with
    :returns: validator function which takes name and value arguments
    """
    jsonschema.Draft4Validator.check_schema(schema)

    return functools.partial(_validate_schema, schema=schema)


def _validate_dict(name, value, validators):
    if value is None:
        return
    _validate_types(name, value, (dict, ))

    for k, v in validators.items():
        if k in value:
            value[k] = v(name=k, value=value[k])

    return value


def dict_valid(**validators):
    """Return a validator function which validates dict fields

    Validators will replace the value with the validation result. Any dict
    item which has no validator is ignored. When a key is missing in the value
    then the corresponding validator will not be run.

    :param: validators dict where the key is a dict key to validate and the
            value is a validator function to run on that value
    :returns: validator function which takes name and value arguments
    """
    return functools.partial(_validate_dict, validators=validators)


def _validate_types(name, value, types):
    if not isinstance(value, types):
        str_types = ', '.join([str(t) for t in types])
        raise exception.InvalidParameterValue(
            _('Expected types %s for %s: %s') % (str_types, name, value))
    return value


def types(*types):
    """Return a validator function which checks the value is one of the types

    :param: types one or more types to use for the isinstance test
    :returns: validator function which takes name and value arguments
    """
    # Replace None with the None type
    types = tuple((type(None) if tp is None else tp) for tp in types)
    return functools.partial(_validate_types, types=types)


def _apply_validator(name, value, val_functions):
    if callable(val_functions):
        return val_functions(name, value)

    for v in val_functions:
        value = v(name, value)
    return value


def _inspect(function):
    sig = inspect.signature(function)
    param_keyword = None  # **kwargs parameter
    param_positional = None  # *args parameter
    params = []

    for param in sig.parameters.values():
        if param.kind == inspect.Parameter.POSITIONAL_OR_KEYWORD:
            params.append(param)
        elif param.kind == inspect.Parameter.VAR_KEYWORD:
            param_keyword = param
        elif param.kind == inspect.Parameter.VAR_POSITIONAL:
            param_positional = param
        else:
            assert False, 'Unsupported parameter kind %s %s' % (
                param.name, param.kind
            )
    return params, param_positional, param_keyword


def validate(*args, **kwargs):
    """Decorator which validates and transforms function arguments

    """
    assert not args, 'Validators must be specified by argument name'
    assert kwargs, 'No validators specified'
    validators = kwargs

    def inner_function(function):
        params, param_positional, param_keyword = _inspect(function)

        @functools.wraps(function)
        def inner_check_args(*args, **kwargs):
            args = list(args)
            args_len = len(args)
            kwargs_next = {}
            next_arg_index = 0

            if not param_keyword:
                # ensure each named argument belongs to a param
                kwarg_keys = set(kwargs)
                param_names = set(p.name for p in params)
                extra_args = kwarg_keys.difference(param_names)
                if extra_args:
                    raise exception.InvalidParameterValue(
                        _('Unexpected arguments: %s') % ', '.join(extra_args))

            for i, param in enumerate(params):

                if i == 0 and param.name == 'self':
                    # skip validating self
                    continue

                val_function = validators.get(param.name)
                if not val_function:
                    continue

                if i < args_len:
                    # validate positional argument
                    args[i] = val_function(param.name, args[i])
                    next_arg_index = i + 1

                elif param.name in kwargs:
                    # validate keyword argument
                    kwargs_next[param.name] = val_function(
                        param.name, kwargs.pop(param.name))
                elif param.default == inspect.Parameter.empty:
                    # no argument was provided, and there is no default
                    # in the parameter, so this is a mandatory argument
                    raise exception.MissingParameterValue(
                        _('Missing mandatory parameter: %s') % param.name)

            if param_positional:
                # handle validating *args
                val_function = validators.get(param_positional.name)
                remaining = args[next_arg_index:]
                if val_function and remaining:
                    args = args[:next_arg_index]
                    args.extend(val_function(param_positional.name, remaining))

            # handle validating remaining **kwargs
            if kwargs:
                val_function = (param_keyword
                                and validators.get(param_keyword.name))
                if val_function:
                    kwargs_next.update(
                        val_function(param_keyword.name, kwargs))
                else:
                    # make sure unvalidated keyword arguments are kept
                    kwargs_next.update(kwargs)

            return function(*args, **kwargs_next)
        return inner_check_args
    return inner_function


patch = schema({
    'type': 'array',
    'items': {
        'type': 'object',
        'properties': {
            'path': {'type': 'string', 'pattern': '^(/[\\w-]+)+$'},
            'op': {'type': 'string', 'enum': ['add', 'replace', 'remove']},
            'value': {}
        },
        'additionalProperties': False,
        'required': ['op', 'path']
    }
})
"""Validate a patch API operation"""
