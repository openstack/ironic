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

import datetime
import functools
from http import client as http_client
import inspect
import json
import sys
import traceback

from oslo_config import cfg
from oslo_log import log
import pecan
from webob import static

from ironic.api import args as api_args
from ironic.api import functions
from ironic.api import types as atypes

LOG = log.getLogger(__name__)


class JSonRenderer(object):
    @staticmethod
    def __init__(path, extra_vars):
        pass

    @staticmethod
    def render(template_path, namespace):
        if 'faultcode' in namespace:
            return encode_error(None, namespace)
        result = encode_result(
            namespace['result'],
            namespace['datatype']
        )
        return result


pecan.templating._builtin_renderers['wsmejson'] = JSonRenderer

pecan_json_decorate = pecan.expose(
    template='wsmejson:',
    content_type='application/json',
    generic=False)


def expose(*args, **kwargs):
    sig = functions.signature(*args, **kwargs)

    def decorate(f):
        sig(f)
        funcdef = functions.FunctionDefinition.get(f)
        funcdef.resolve_types(atypes.registry)

        @functools.wraps(f)
        def callfunction(self, *args, **kwargs):
            return_type = funcdef.return_type

            try:
                args, kwargs = api_args.get_args(
                    funcdef, args, kwargs, pecan.request.params,
                    pecan.request.body, pecan.request.content_type
                )
                result = f(self, *args, **kwargs)

                # NOTE: Support setting of status_code with default 201
                pecan.response.status = funcdef.status_code
                if isinstance(result, atypes.PassthruResponse):
                    pecan.response.status = result.status_code

                    # NOTE(lucasagomes): If the return code is 204
                    # (No Response) we have to make sure that we are not
                    # returning anything in the body response and the
                    # content-length is 0
                    if result.status_code == 204:
                        return_type = None

                    if callable(getattr(result.obj, 'read', None)):
                        # Stream the files-like data directly to the response
                        pecan.response.app_iter = static.FileIter(result.obj)
                        return_type = None
                        result = None
                    else:
                        result = result.obj

            except Exception:
                try:
                    exception_info = sys.exc_info()
                    orig_exception = exception_info[1]
                    orig_code = getattr(orig_exception, 'code', None)
                    data = format_exception(
                        exception_info,
                        cfg.CONF.debug_tracebacks_in_api
                    )
                finally:
                    del exception_info

                if orig_code and orig_code in http_client.responses:
                    pecan.response.status = orig_code
                else:
                    pecan.response.status = 500

                return data

            if return_type is None:
                pecan.request.pecan['content_type'] = None
                pecan.response.content_type = None
                return ''

            return dict(
                datatype=return_type,
                result=result
            )

        pecan_json_decorate(callfunction)
        pecan.util._cfg(callfunction)['argspec'] = inspect.getfullargspec(f)
        callfunction._wsme_definition = funcdef
        return callfunction

    return decorate


def tojson(datatype, value):
    """A generic converter from python to jsonify-able datatypes.

    """
    if value is None:
        return None
    if isinstance(datatype, atypes.ArrayType):
        return [tojson(datatype.item_type, item) for item in value]
    if isinstance(datatype, atypes.DictType):
        return dict((
            (tojson(datatype.key_type, item[0]),
                tojson(datatype.value_type, item[1]))
            for item in value.items()
        ))
    if isinstance(value, datetime.datetime):
        return value.isoformat()
    if atypes.iscomplex(datatype):
        d = dict()
        for attr in atypes.list_attributes(datatype):
            attr_value = getattr(value, attr.key)
            if attr_value is not atypes.Unset:
                d[attr.name] = tojson(attr.datatype, attr_value)
        return d
    if isinstance(datatype, atypes.UserType):
        return tojson(datatype.basetype, datatype.tobasetype(value))
    return value


def encode_result(value, datatype, **options):
    jsondata = tojson(datatype, value)
    return json.dumps(jsondata)


def encode_error(context, errordetail):
    return json.dumps(errordetail)


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


class validate(object):
    """Decorator that define the arguments types of a function.


    Example::

        class MyController(object):
            @expose(str)
            @validate(datetime.date, datetime.time)
            def format(self, d, t):
                return d.isoformat() + ' ' + t.isoformat()
    """
    def __init__(self, *param_types):
        self.param_types = param_types

    def __call__(self, func):
        argspec = functions.getargspec(func)
        fd = functions.FunctionDefinition.get(func)
        fd.set_arg_types(argspec, self.param_types)
        return func
