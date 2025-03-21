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

"""API request/response validating middleware."""

import functools
import inspect
import typing as ty

import jsonschema.exceptions
from oslo_config import cfg
from oslo_log import log
from oslo_serialization import jsonutils
from webob import exc as webob_exc

from ironic import api
from ironic.api.validation import validators
from ironic.common.i18n import _

CONF = cfg.CONF
LOG = log.getLogger(__name__)


def api_version(
    min_version: ty.Optional[int],
    max_version: ty.Optional[int] = None,
    message: ty.Optional[str] = None,
    exception_class: ty.Type[webob_exc.HTTPException] = webob_exc.HTTPNotFound,
):
    """Decorator for marking lower and upper bounds on API methods.

    :param min_version: An integer representing the minimum API version that
        the API is available under.
    :param max_version: An integer representing the maximum API version that
        the API is available under.
    :param message: A message to return if the API is not supported.
    :param exception_class: The exception class to raise if the API version is
        not supported (default is HTTPNotFound).
    """

    # Ensure the provided status code is valid for the given exception class
    assert isinstance(
        exception_class,
        type(webob_exc.HTTPException)
    ), (
        "Invalid exception class provided, must be a "
        "subclass of webob_exc.HTTPException."
    )

    def add_validator(func):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            # Version checks
            if (
                min_version and not api.request.version.minor >= min_version
            ) or (
                max_version and not api.request.version.minor <= max_version
            ):
                # Raise provided exception with localized message
                raise exception_class(
                    detail=_(
                        message
                        or 'The API is not supported for this version'
                    )
                )

            return func(*args, **kwargs)

        wrapper.min_version = min_version
        wrapper.max_version = max_version

        return wrapper

    return add_validator


class Schemas:
    """A microversion-aware schema container.

    Allow definition and retrieval of schemas on a microversion-aware basis.
    """

    def __init__(self) -> None:
        self._schemas: list[
            tuple[dict[str, object], ty.Optional[int], ty.Optional[int]]
        ] = []

    def add_schema(
        self,
        schema: tuple[dict[str, object]],
        min_version: ty.Optional[int],
        max_version: ty.Optional[int],
    ) -> None:
        self._schemas.append((schema, min_version, max_version))

    def __call__(self) -> ty.Optional[dict[str, object]]:
        for schema, min_version, max_version in self._schemas:
            if (
                min_version and not api.request.version.minor >= min_version
            ) or (
                max_version and not api.request.version.minor <= max_version
            ):
                continue

            return schema

        return None


def _schema_validator(
    schema: ty.Dict[str, ty.Any],
    target: ty.Dict[str, ty.Any],
    min_version: ty.Optional[int],
    max_version: ty.Optional[int],
    is_body: bool = True,
):
    """A helper method to execute JSON Schema Validation.

    This method checks the request version whether matches the specified
    ``max_version`` and ``min_version``. If the version range matches the
    request, we validate ``schema`` against ``target``. A failure will result
    in ``ValidationError`` being raised.

    :param schema: The JSON Schema schema used to validate the target.
    :param target: The target to be validated by the schema.
    :param min_version: An integer indicating the minimum API version
        ``schema`` applies against.
    :param max_version: An integer indicating the maximum API version
        ``schema`` applies against.
    :param args: Positional arguments which passed into original method.
    :param kwargs: Keyword arguments which passed into original method.
    :param is_body: Whether ``target`` is a HTTP request body or not.
    :returns: None.
    :raises: ``ValidationError`` if validation fails.
    """
    # Only validate against the schema if it lies within
    # the version range specified. Note that if both min
    # and max are not specified the validator will always
    # be run.
    if (
        (min_version and api.request.version.minor < min_version)
        or (max_version and api.request.version.minor > max_version)
    ):
        return

    schema_validator = validators.SchemaValidator(schema, is_body=is_body)
    schema_validator.validate(target)


def _extract_parameters(function):
    sig = inspect.signature(function)
    params = []

    for param in sig.parameters.values():
        if param.kind == inspect.Parameter.POSITIONAL_OR_KEYWORD:
            if param.name == 'self':  # skip validating self
                continue

            params.append(param)
    return params


def request_parameter_schema(
    schema: ty.Dict[str, ty.Any],
    min_version: ty.Optional[int] = None,
    max_version: ty.Optional[int] = None,
):
    """Decorator for registering a request parameter schema on API methods.

    ``schema`` will be used for validating request parameters just before
    the API method is executed.

    :param schema: The JSON Schema schema used to validate the target.
    :param min_version: An integer indicating the minimum API version
        ``schema`` applies against.
    :param max_version: An integer indicating the maximum API version
        ``schema`` applies against.
    """

    def add_validator(func):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            # we need to convert positional arguments to a dict mapping token
            # name to value so that we have a reference to compare against
            parameters = _extract_parameters(func)
            if func.__name__ in ('patch', 'post'):
                # if this a create or update method, we need to ignore the
                # request body parameter
                parameters = parameters[:-1]

            parameters = {
                p.name: args[i + 1] for i, p in enumerate(parameters)
                if p.name != '_' and p.default is p.empty
            }
            _schema_validator(
                schema,
                parameters,
                min_version,
                max_version,
                is_body=True,
            )
            return func(*args, **kwargs)

        if hasattr(func, 'arguments_transformed'):
            raise RuntimeError(
                'The ironic.common.args.validate decorator must wrap (come '
                'before) the schema decorators to ensure side effects occur.'
            )

        if not hasattr(wrapper, 'request_parameter_schemas'):
            wrapper.request_parameter_schemas = Schemas()

        wrapper.request_parameter_schemas.add_schema(
            schema, min_version, max_version
        )

        return wrapper

    return add_validator


def request_query_schema(
    schema: ty.Dict[str, ty.Any],
    min_version: ty.Optional[int] = None,
    max_version: ty.Optional[int] = None,
):
    """Decorator for registering a request query string schema on API methods.

    ``schema`` will be used for validating request query strings just before
    the API method is executed.

    :param schema: The JSON Schema schema used to validate the target.
    :param min_version: An integer indicating the minimum API version
        ``schema`` applies against.
    :param max_version: An integer indicating the maximum API version
        ``schema`` applies against.
    """

    def add_validator(func):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            _schema_validator(
                schema,
                kwargs,
                min_version,
                max_version,
                is_body=True,
            )
            return func(*args, **kwargs)

        if hasattr(func, 'arguments_transformed'):
            raise RuntimeError(
                'The ironic.common.args.validate decorator must wrap (come '
                'before) the schema decorators to ensure side effects occur.'
            )

        if not hasattr(wrapper, 'request_query_schemas'):
            wrapper.request_query_schemas = Schemas()

        wrapper.request_query_schemas.add_schema(
            schema, min_version, max_version
        )

        return wrapper

    return add_validator


def request_body_schema(
    schema: ty.Dict[str, ty.Any],
    min_version: ty.Optional[int] = None,
    max_version: ty.Optional[int] = None,
):
    """Decorator for registering a request body schema on API methods.

    ``schema`` will be used for validating the request body just before the API
    method is executed.

    :param schema: The JSON Schema schema used to validate the target.
    :param min_version: An integer indicating the minimum API version
        ``schema`` applies against.
    :param max_version: An integer indicating the maximum API version
        ``schema`` applies against.
    """

    def add_validator(func):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            parameters = _extract_parameters(func)
            if not parameters:
                # TODO(stephenfin): this would be a better check if we
                # distinguished between 'create' operations (which should have
                # at least one parameter, the body) and "update" operations
                # (which should have at least two, the IDs and the body)
                raise RuntimeError(
                    'The ironic.api.method.body decorator must be placed '
                    'outside the validation helpers to ensure it runs first.'
                )

            _schema_validator(
                schema,
                # The body argument will always be the last one
                kwargs[parameters[-1].name],
                min_version,
                max_version,
                is_body=True,
            )
            return func(*args, **kwargs)

        if hasattr(func, 'arguments_transformed'):
            raise RuntimeError(
                'The ironic.common.args.validate decorator must wrap (come '
                'before) the schema decorators to ensure side effects occur.'
            )

        if not hasattr(wrapper, 'request_body_schemas'):
            wrapper.request_body_schemas = Schemas()

        wrapper.request_body_schemas.add_schema(
            schema, min_version, max_version
        )

        return wrapper

    return add_validator


def response_body_schema(
    schema: ty.Dict[str, ty.Any],
    min_version: ty.Optional[int] = None,
    max_version: ty.Optional[int] = None,
):
    """Decorator for registering a response body schema on API methods.

    ``schema`` will be used for validating the response body just after the API
    method is executed.

    :param schema: The JSON Schema schema used to validate the target.
    :param min_version: An integer indicating the minimum API version
        ``schema`` applies against.
    :param max_version: An integer indicating the maximum API version
        ``schema`` applies against.
    """

    def add_validator(func):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            response = func(*args, **kwargs)

            if CONF.api.response_validation == 'ignore':
                # don't waste our time checking anything if we're ignoring
                # schema errors
                return response

            # FIXME(stephenfin): How is ironic/pecan doing jsonification? The
            # below will fail on e.g. date-time fields

            # NOTE(stephenfin): If our response is an object, we need to
            # serialize and deserialize to convert e.g. date-time to strings
            _body = jsonutils.dumps(response)

            if _body == b'':
                body = None
            else:
                body = jsonutils.loads(_body)

            try:
                _schema_validator(
                    schema,
                    body,
                    min_version,
                    max_version,
                    is_body=True,
                )
            except jsonschema.exceptions.ValidationError:
                if CONF.api.response_validation == 'warn':
                    LOG.exception('Schema failed to validate')
                else:
                    raise

            return response

        if hasattr(func, 'arguments_transformed'):
            raise RuntimeError(
                'The ironic.common.args.validate decorator must wrap (come '
                'before) the schema decorators to ensure side effects occur.'
            )

        if not hasattr(wrapper, 'response_body_schemas'):
            wrapper.response_body_schemas = Schemas()

        wrapper.response_body_schemas.add_schema(
            schema, min_version, max_version
        )

        return wrapper

    return add_validator
