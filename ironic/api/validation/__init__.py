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

import functools
import typing as ty

from webob import exc as webob_exc

from ironic import api
from ironic.common.i18n import _


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
