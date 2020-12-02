#
# Copyright 2015 Rackspace, Inc
# All Rights Reserved
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

import functools
from http import client as http_client
import json
import sys
import traceback

from oslo_config import cfg
from oslo_log import log
import pecan

LOG = log.getLogger(__name__)


pecan_json_decorate = pecan.expose(
    content_type='application/json',
    generic=False)


def expose(status_code=None):

    def decorate(f):

        @functools.wraps(f)
        def callfunction(self, *args, **kwargs):
            try:
                result = f(self, *args, **kwargs)
                if status_code:
                    pecan.response.status = status_code

            except Exception:
                try:
                    exception_info = sys.exc_info()
                    orig_exception = exception_info[1]
                    orig_code = getattr(orig_exception, 'code', None)
                    result = format_exception(
                        exception_info,
                        cfg.CONF.debug_tracebacks_in_api
                    )
                finally:
                    del exception_info

                if orig_code and orig_code in http_client.responses:
                    pecan.response.status = orig_code
                else:
                    pecan.response.status = 500

            def _empty():
                # This is for a pecan workaround originally in WSME,
                # but the original issue description is in an issue tracker
                # that is now offline
                pecan.request.pecan['content_type'] = None
                pecan.response.content_type = None

            # never return content for NO_CONTENT
            if pecan.response.status_code == 204:
                return _empty()

            # don't encode None for ACCEPTED responses
            if result is None and pecan.response.status_code == 202:
                return _empty()

            return json.dumps(result)

        pecan_json_decorate(callfunction)
        return callfunction

    return decorate


def body(body_arg):
    """Decorator which places HTTP request body JSON into a method argument

    :param body_arg: Name of argument to populate with body JSON
    """

    def inner_function(function):

        @functools.wraps(function)
        def inner_body(*args, **kwargs):

            if pecan.request.body:
                data = pecan.request.json
            else:
                data = {}
            if isinstance(data, dict):
                # remove any keyword arguments which pecan has
                # extracted from the body
                for field in data.keys():
                    kwargs.pop(field, None)

            kwargs[body_arg] = data

            return function(*args, **kwargs)
        return inner_body
    return inner_function


def format_exception(excinfo, debug=False):
    """Extract informations that can be sent to the client."""
    error = excinfo[1]
    code = getattr(error, 'code', None)
    if code and code in http_client.responses and (400 <= code < 500):
        faultstring = (error.faultstring if hasattr(error, 'faultstring')
                       else str(error))
        faultcode = getattr(error, 'faultcode', 'Client')
        r = dict(faultcode=faultcode,
                 faultstring=faultstring)
        LOG.debug("Client-side error: %s", r['faultstring'])
        r['debuginfo'] = None
        return r
    else:
        faultstring = str(error)
        debuginfo = "\n".join(traceback.format_exception(*excinfo))

        LOG.error('Server-side error: "%s". Detail: \n%s',
                  faultstring, debuginfo)

        faultcode = getattr(error, 'faultcode', 'Server')
        r = dict(faultcode=faultcode, faultstring=faultstring)
        if debug:
            r['debuginfo'] = debuginfo
        else:
            r['debuginfo'] = None
        return r
