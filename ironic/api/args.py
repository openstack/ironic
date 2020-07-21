# Copyright 2011-2019 the WSME authors and contributors
# (See https://opendev.org/x/wsme/)
#
# This module is part of WSME and is also released under
# the MIT License: http://www.opensource.org/licenses/mit-license.php
#
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

import datetime
import decimal
import json
import logging

from dateutil import parser as dateparser

from ironic.api import types as atypes
from ironic.common import exception

LOG = logging.getLogger(__name__)


CONTENT_TYPE = 'application/json'
ACCEPT_CONTENT_TYPES = [
    CONTENT_TYPE,
    'text/javascript',
    'application/javascript'
]
ENUM_TRUE = ('true', 't', 'yes', 'y', 'on', '1')
ENUM_FALSE = ('false', 'f', 'no', 'n', 'off', '0')


def fromjson_array(datatype, value):
    if not isinstance(value, list):
        raise ValueError("Value not a valid list: %s" % value)
    return [fromjson(datatype.item_type, item) for item in value]


def fromjson_dict(datatype, value):
    if not isinstance(value, dict):
        raise ValueError("Value not a valid dict: %s" % value)
    return dict((
        (fromjson(datatype.key_type, item[0]),
            fromjson(datatype.value_type, item[1]))
        for item in value.items()))


def fromjson_bool(value):
    if isinstance(value, (int, bool)):
        return bool(value)
    if value in ENUM_TRUE:
        return True
    if value in ENUM_FALSE:
        return False
    raise ValueError("Value not an unambiguous boolean: %s" % value)


def fromjson(datatype, value):
    """A generic converter from json base types to python datatype.

    """
    if value is None:
        return None

    if isinstance(datatype, atypes.ArrayType):
        return fromjson_array(datatype, value)

    if isinstance(datatype, atypes.DictType):
        return fromjson_dict(datatype, value)

    if datatype is bytes:
        if isinstance(value, (str, int, float)):
            return str(value).encode('utf8')
        return value

    if datatype is str:
        if isinstance(value, bytes):
            return value.decode('utf-8')
        return value

    if datatype in (int, float):
        return datatype(value)

    if datatype is bool:
        return fromjson_bool(value)

    if datatype is decimal.Decimal:
        return decimal.Decimal(value)

    if datatype is datetime.datetime:
        return dateparser.parse(value)

    if atypes.iscomplex(datatype):
        return fromjson_complex(datatype, value)

    if atypes.isusertype(datatype):
        return datatype.frombasetype(fromjson(datatype.basetype, value))

    return value


def fromjson_complex(datatype, value):
    obj = datatype()
    attributes = atypes.list_attributes(datatype)

    # Here we check that all the attributes in the value are also defined
    # in our type definition, otherwise we raise an Error.
    v_keys = set(value.keys())
    a_keys = set(adef.name for adef in attributes)
    if not v_keys <= a_keys:
        raise exception.UnknownAttribute(None, v_keys - a_keys)

    for attrdef in attributes:
        if attrdef.name in value:
            try:
                val_fromjson = fromjson(attrdef.datatype,
                                        value[attrdef.name])
            except exception.UnknownAttribute as e:
                e.add_fieldname(attrdef.name)
                raise
            if getattr(attrdef, 'readonly', False):
                raise exception.InvalidInput(attrdef.name, val_fromjson,
                                             "Cannot set read only field.")
            setattr(obj, attrdef.key, val_fromjson)
        elif attrdef.mandatory:
            raise exception.InvalidInput(attrdef.name, None,
                                         "Mandatory field missing.")

    return atypes.validate_value(datatype, obj)


def parse(s, datatypes, bodyarg, encoding='utf8'):
    jload = json.load
    if not hasattr(s, 'read'):
        if isinstance(s, bytes):
            s = s.decode(encoding)
        jload = json.loads
    try:
        jdata = jload(s)
    except ValueError:
        raise exception.ClientSideError("Request is not in valid JSON format")
    if bodyarg:
        argname = list(datatypes.keys())[0]
        try:
            kw = {argname: fromjson(datatypes[argname], jdata)}
        except ValueError as e:
            raise exception.InvalidInput(argname, jdata, e.args[0])
        except exception.UnknownAttribute as e:
            # We only know the fieldname at this level, not in the
            # called function. We fill in this information here.
            e.add_fieldname(argname)
            raise
    else:
        kw = {}
        extra_args = []
        if not isinstance(jdata, dict):
            raise exception.ClientSideError("Request must be a JSON dict")
        for key in jdata:
            if key not in datatypes:
                extra_args.append(key)
            else:
                try:
                    kw[key] = fromjson(datatypes[key], jdata[key])
                except ValueError as e:
                    raise exception.InvalidInput(key, jdata[key], e.args[0])
                except exception.UnknownAttribute as e:
                    # We only know the fieldname at this level, not in the
                    # called function. We fill in this information here.
                    e.add_fieldname(key)
                    raise
        if extra_args:
            raise exception.UnknownArgument(', '.join(extra_args))
    return kw


def from_param(datatype, value):
    if datatype is datetime.datetime:
        return dateparser.parse(value) if value else None

    if isinstance(datatype, atypes.UserType):
        return datatype.frombasetype(
            from_param(datatype.basetype, value))

    if isinstance(datatype, atypes.ArrayType):
        if value is None:
            return value
        return [
            from_param(datatype.item_type, item)
            for item in value
        ]

    return datatype(value) if value is not None else None


def from_params(datatype, params, path, hit_paths):
    if isinstance(datatype, atypes.ArrayType):
        return array_from_params(datatype, params, path, hit_paths)

    if isinstance(datatype, atypes.UserType):
        return usertype_from_params(datatype, params, path, hit_paths)

    if path in params:
        assert not isinstance(datatype, atypes.DictType), \
            'DictType unsupported'
        assert not atypes.iscomplex(datatype) or datatype is atypes.File, \
            'complex type unsupported'
        hit_paths.add(path)
        return from_param(datatype, params[path])
    return atypes.Unset


def array_from_params(datatype, params, path, hit_paths):
    if hasattr(params, 'getall'):
        # webob multidict
        def getall(params, path):
            return params.getall(path)
    elif hasattr(params, 'getlist'):
        # werkzeug multidict
        def getall(params, path):  # noqa
            return params.getlist(path)
    if path in params:
        hit_paths.add(path)
        return [
            from_param(datatype.item_type, value)
            for value in getall(params, path)]

    return atypes.Unset


def usertype_from_params(datatype, params, path, hit_paths):
    if path in params:
        hit_paths.add(path)
        value = from_param(datatype.basetype, params[path])
        if value is not atypes.Unset:
            return datatype.frombasetype(value)
    return atypes.Unset


def args_from_args(funcdef, args, kwargs):
    newargs = []
    for argdef, arg in zip(funcdef.arguments[:len(args)], args):
        try:
            newargs.append(from_param(argdef.datatype, arg))
        except Exception as e:
            if isinstance(argdef.datatype, atypes.UserType):
                datatype_name = argdef.datatype.name
            elif isinstance(argdef.datatype, type):
                datatype_name = argdef.datatype.__name__
            else:
                datatype_name = argdef.datatype.__class__.__name__
            raise exception.InvalidInput(
                argdef.name,
                arg,
                "unable to convert to %(datatype)s. Error: %(error)s" % {
                    'datatype': datatype_name, 'error': e})
    newkwargs = {}
    for argname, value in kwargs.items():
        newkwargs[argname] = from_param(
            funcdef.get_arg(argname).datatype, value
        )
    return newargs, newkwargs


def args_from_params(funcdef, params):
    kw = {}
    hit_paths = set()
    for argdef in funcdef.arguments:
        value = from_params(
            argdef.datatype, params, argdef.name, hit_paths)
        if value is not atypes.Unset:
            kw[argdef.name] = value
    paths = set(params.keys())
    unknown_paths = paths - hit_paths
    if '__body__' in unknown_paths:
        unknown_paths.remove('__body__')
    if not funcdef.ignore_extra_args and unknown_paths:
        raise exception.UnknownArgument(', '.join(unknown_paths))
    return [], kw


def args_from_body(funcdef, body, mimetype):
    if funcdef.body_type is not None:
        datatypes = {funcdef.arguments[-1].name: funcdef.body_type}
    else:
        datatypes = dict(((a.name, a.datatype) for a in funcdef.arguments))

    if not body:
        return (), {}

    if mimetype == "application/x-www-form-urlencoded":
        # the parameters should have been parsed in params
        return (), {}
    elif mimetype not in ACCEPT_CONTENT_TYPES:
        raise exception.ClientSideError("Unknown mimetype: %s" % mimetype,
                                        status_code=415)

    try:
        kw = parse(
            body, datatypes, bodyarg=funcdef.body_type is not None
        )
    except exception.UnknownArgument:
        if not funcdef.ignore_extra_args:
            raise
        kw = {}

    return (), kw


def combine_args(funcdef, akw, allow_override=False):
    newargs, newkwargs = [], {}
    for args, kwargs in akw:
        for i, arg in enumerate(args):
            n = funcdef.arguments[i].name
            if not allow_override and n in newkwargs:
                raise exception.ClientSideError(
                    "Parameter %s was given several times" % n)
            newkwargs[n] = arg
        for name, value in kwargs.items():
            n = str(name)
            if not allow_override and n in newkwargs:
                raise exception.ClientSideError(
                    "Parameter %s was given several times" % n)
            newkwargs[n] = value
    return newargs, newkwargs


def get_args(funcdef, args, kwargs, params, body, mimetype):
    """Combine arguments from multiple sources

    Combine arguments from :
    * the host framework args and kwargs
    * the request params
    * the request body

    Note that the host framework args and kwargs can be overridden
    by arguments from params of body

    """
    # get the body from params if not given directly
    if not body and '__body__' in params:
        body = params['__body__']

    # extract args from the host args and kwargs
    from_args = args_from_args(funcdef, args, kwargs)

    # extract args from the request parameters
    from_params = args_from_params(funcdef, params)

    # extract args from the request body
    from_body = args_from_body(funcdef, body, mimetype)

    # combine params and body arguments
    from_params_and_body = combine_args(
        funcdef,
        (from_params, from_body)
    )

    args, kwargs = combine_args(
        funcdef,
        (from_args, from_params_and_body),
        allow_override=True
    )
    check_arguments(funcdef, args, kwargs)
    return args, kwargs


def check_arguments(funcdef, args, kw):
    """Check if some arguments are missing"""
    assert len(args) == 0
    for arg in funcdef.arguments:
        if arg.mandatory and arg.name not in kw:
            raise exception.MissingArgument(arg.name)
