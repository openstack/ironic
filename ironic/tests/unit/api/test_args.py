# Copyright 2020 Red Hat, Inc.
# All Rights Reserved.
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
import decimal
import io

from webob import multidict

from ironic.api import args
from ironic.api.controllers.v1 import types
from ironic.api import functions
from ironic.api import types as atypes
from ironic.common import exception
from ironic.tests import base as test_base


class Obj(atypes.Base):

    id = atypes.wsattr(int, mandatory=True)
    name = str
    readonly_field = atypes.wsattr(str, readonly=True)
    default_field = atypes.wsattr(str, default='foo')
    unset_me = str


class NestedObj(atypes.Base):
    o = Obj


class TestArgs(test_base.TestCase):

    def test_fromjson_array(self):
        atype = atypes.ArrayType(int)
        self.assertEqual(
            [0, 1, 1234, None],
            args.fromjson_array(atype, [0, '1', '1_234', None])
        )
        self.assertRaises(ValueError, args.fromjson_array,
                          atype, ['one', 'two', 'three'])
        self.assertRaises(ValueError, args.fromjson_array,
                          atype, 'one')

    def test_fromjson_dict(self):
        dtype = atypes.DictType(str, int)
        self.assertEqual({
            'zero': 0,
            'one': 1,
            'etc': 1234,
            'none': None
        }, args.fromjson_dict(dtype, {
            'zero': 0,
            'one': '1',
            'etc': '1_234',
            'none': None
        }))

        self.assertRaises(ValueError, args.fromjson_dict,
                          dtype, [])
        self.assertRaises(ValueError, args.fromjson_dict,
                          dtype, {'one': 'one'})

    def test_fromjson_bool(self):
        for b in (1, 2, True, 'true', 't', 'yes', 'y', 'on', '1'):
            self.assertTrue(args.fromjson_bool(b))
        for b in (0, False, 'false', 'f', 'no', 'n', 'off', '0'):
            self.assertFalse(args.fromjson_bool(b))
        for b in ('yup', 'yeet', 'NOPE', 3.14):
            self.assertRaises(ValueError, args.fromjson_bool, b)

    def test_fromjson(self):
        # parse None
        self.assertIsNone(args.fromjson(None, None))

        # parse array
        atype = atypes.ArrayType(int)
        self.assertEqual(
            [0, 1, 1234, None],
            args.fromjson(atype, [0, '1', '1_234', None])
        )

        # parse dict
        dtype = atypes.DictType(str, int)
        self.assertEqual({
            'zero': 0,
            'one': 1,
            'etc': 1234,
            'none': None
        }, args.fromjson(dtype, {
            'zero': 0,
            'one': '1',
            'etc': '1_234',
            'none': None
        }))

        # parse bytes
        self.assertEqual(
            b'asdf',
            args.fromjson(bytes, b'asdf')
        )
        self.assertEqual(
            b'asdf',
            args.fromjson(bytes, 'asdf')
        )
        self.assertEqual(
            b'33',
            args.fromjson(bytes, 33)
        )
        self.assertEqual(
            b'3.14',
            args.fromjson(bytes, 3.14)
        )

        # parse str
        self.assertEqual(
            'asdf',
            args.fromjson(str, b'asdf')
        )
        self.assertEqual(
            'asdf',
            args.fromjson(str, 'asdf')
        )

        # parse int/float
        self.assertEqual(
            3,
            args.fromjson(int, '3')
        )
        self.assertEqual(
            3,
            args.fromjson(int, 3)
        )
        self.assertEqual(
            3.14,
            args.fromjson(float, 3.14)
        )

        # parse bool
        self.assertFalse(args.fromjson(bool, 'no'))
        self.assertTrue(args.fromjson(bool, 'yes'))

        # parse decimal
        self.assertEqual(
            decimal.Decimal(3.14),
            args.fromjson(decimal.Decimal, 3.14)
        )

        # parse datetime
        expected = datetime.datetime(2015, 8, 13, 11, 38, 9, 496475)
        self.assertEqual(
            expected,
            args.fromjson(datetime.datetime, '2015-08-13T11:38:09.496475')
        )

        # parse complex
        n = args.fromjson(NestedObj, {'o': {
            'id': 1234,
            'name': 'an object'
        }})
        self.assertIsInstance(n.o, Obj)
        self.assertEqual(1234, n.o.id)
        self.assertEqual('an object', n.o.name)
        self.assertEqual('foo', n.o.default_field)

        # parse usertype
        self.assertEqual(
            ['0', '1', '2', 'three'],
            args.fromjson(types.listtype, '0,1, 2, three')
        )

    def test_fromjson_complex(self):
        n = args.fromjson_complex(NestedObj, {'o': {
            'id': 1234,
            'name': 'an object'
        }})
        self.assertIsInstance(n.o, Obj)
        self.assertEqual(1234, n.o.id)
        self.assertEqual('an object', n.o.name)
        self.assertEqual('foo', n.o.default_field)

        e = self.assertRaises(exception.UnknownAttribute,
                              args.fromjson_complex,
                              Obj, {'ooo': {}})
        self.assertEqual({'ooo'}, e.attributes)

        e = self.assertRaises(exception.InvalidInput, args.fromjson_complex,
                              Obj,
                              {'name': 'an object'})
        self.assertEqual('id', e.fieldname)
        self.assertEqual('Mandatory field missing.', e.msg)

        e = self.assertRaises(exception.InvalidInput, args.fromjson_complex,
                              Obj,
                              {'id': 1234, 'readonly_field': 'foo'})
        self.assertEqual('readonly_field', e.fieldname)
        self.assertEqual('Cannot set read only field.', e.msg)

    def test_parse(self):
        # source as bytes
        s = b'{"o": {"id": 1234, "name": "an object"}}'

        # test bodyarg=True
        n = args.parse(s, {"o": NestedObj}, True)['o']
        self.assertEqual(1234, n.o.id)
        self.assertEqual('an object', n.o.name)

        # source as file
        s = io.StringIO('{"o": {"id": 1234, "name": "an object"}}')

        # test bodyarg=False
        n = args.parse(s, {"o": Obj}, False)['o']
        self.assertEqual(1234, n.id)
        self.assertEqual('an object', n.name)

        # fromjson ValueError
        s = '{"o": ["id", "name"]}'
        self.assertRaises(exception.InvalidInput, args.parse,
                          s, {"o": atypes.DictType(str, str)}, False)
        s = '["id", "name"]'
        self.assertRaises(exception.InvalidInput, args.parse,
                          s, {"o": atypes.DictType(str, str)}, True)

        # fromjson UnknownAttribute
        s = '{"o": {"foo": "bar", "id": 1234, "name": "an object"}}'
        self.assertRaises(exception.UnknownAttribute, args.parse,
                          s, {"o": NestedObj}, True)
        self.assertRaises(exception.UnknownAttribute, args.parse,
                          s, {"o": Obj}, False)

        # invalid json
        s = '{Sunn O)))}'
        self.assertRaises(exception.ClientSideError, args.parse,
                          s, {"o": Obj}, False)

        # extra args
        s = '{"foo": "bar", "o": {"id": 1234, "name": "an object"}}'
        self.assertRaises(exception.UnknownArgument, args.parse,
                          s, {"o": Obj}, False)

    def test_from_param(self):
        # datetime param
        expected = datetime.datetime(2015, 8, 13, 11, 38, 9, 496475)
        self.assertEqual(
            expected,
            args.from_param(datetime.datetime, '2015-08-13T11:38:09.496475')
        )
        self.assertIsNone(args.from_param(datetime.datetime, None))

        # file param
        self.assertEqual(
            b'foo',
            args.from_param(atypes.File, b'foo').content
        )

        # usertype param
        self.assertEqual(
            ['0', '1', '2', 'three'],
            args.from_param(types.listtype, '0,1, 2, three')
        )

        # array param
        atype = atypes.ArrayType(int)
        self.assertEqual(
            [0, 1, 1234, None],
            args.from_param(atype, [0, '1', '1_234', None])
        )
        self.assertIsNone(args.from_param(atype, None))

        # string param
        self.assertEqual('foo', args.from_param(str, 'foo'))
        self.assertIsNone(args.from_param(str, None))

        # string param with from_params
        hit_paths = set()
        params = multidict.MultiDict(
            foo='bar',
        )
        self.assertEqual(
            'bar',
            args.from_params(str, params, 'foo', hit_paths)
        )
        self.assertEqual({'foo'}, hit_paths)

    def test_array_from_params(self):
        hit_paths = set()
        datatype = atypes.ArrayType(str)
        params = multidict.MultiDict(
            foo='bar',
            one='two'
        )
        self.assertEqual(
            ['bar'],
            args.from_params(datatype, params, 'foo', hit_paths)
        )
        self.assertEqual({'foo'}, hit_paths)
        self.assertEqual(
            ['two'],
            args.array_from_params(datatype, params, 'one', hit_paths)
        )
        self.assertEqual({'foo', 'one'}, hit_paths)

    def test_usertype_from_params(self):
        hit_paths = set()
        datatype = types.listtype
        params = multidict.MultiDict(
            foo='0,1, 2, three',
        )
        self.assertEqual(
            ['0', '1', '2', 'three'],
            args.usertype_from_params(datatype, params, 'foo', hit_paths)
        )
        self.assertEqual(
            ['0', '1', '2', 'three'],
            args.from_params(datatype, params, 'foo', hit_paths)
        )
        self.assertEqual(
            atypes.Unset,
            args.usertype_from_params(datatype, params, 'bar', hit_paths)
        )

    def test_args_from_args(self):

        fromargs = ['one', 2, [0, '1', '2_34']]
        fromkwargs = {'foo': '1, 2, 3'}

        @functions.signature(str, str, int, atypes.ArrayType(int),
                             types.listtype)
        def myfunc(self, first, second, third, foo):
            pass
        funcdef = functions.FunctionDefinition.get(myfunc)

        newargs, newkwargs = args.args_from_args(funcdef, fromargs, fromkwargs)
        self.assertEqual(['one', 2, [0, 1, 234]], newargs)
        self.assertEqual({'foo': ['1', '2', '3']}, newkwargs)

    def test_args_from_params(self):

        @functions.signature(str, str, int, atypes.ArrayType(int),
                             types.listtype)
        def myfunc(self, first, second, third, foo):
            pass
        funcdef = functions.FunctionDefinition.get(myfunc)
        params = multidict.MultiDict(
            foo='0,1, 2, three',
            third='1',
            second='2'
        )
        self.assertEqual(
            ([], {'foo': ['0', '1', '2', 'three'], 'second': 2, 'third': [1]}),
            args.args_from_params(funcdef, params)
        )

        # unexpected param
        params = multidict.MultiDict(bar='baz')
        self.assertRaises(exception.UnknownArgument, args.args_from_params,
                          funcdef, params)

        # no params plus a body
        params = multidict.MultiDict(__body__='')
        self.assertEqual(
            ([], {}),
            args.args_from_params(funcdef, params)
        )

    def test_args_from_body(self):
        @functions.signature(str, body=NestedObj)
        def myfunc(self, nested):
            pass
        funcdef = functions.FunctionDefinition.get(myfunc)
        mimetype = 'application/json'
        body = b'{"o": {"id": 1234, "name": "an object"}}'
        newargs, newkwargs = args.args_from_body(funcdef, body, mimetype)

        self.assertEqual(1234, newkwargs['nested'].o.id)
        self.assertEqual('an object', newkwargs['nested'].o.name)

        self.assertEqual(
            ((), {}),
            args.args_from_body(funcdef, None, mimetype)
        )

        self.assertRaises(exception.ClientSideError, args.args_from_body,
                          funcdef, body, 'application/x-corba')

        self.assertEqual(
            ((), {}),
            args.args_from_body(funcdef, body,
                                'application/x-www-form-urlencoded')
        )

    def test_combine_args(self):

        @functions.signature(str, str, int)
        def myfunc(self, first, second,):
            pass
        funcdef = functions.FunctionDefinition.get(myfunc)

        # empty
        self.assertEqual(
            ([], {}),
            args.combine_args(
                funcdef, (
                    ([], {}),
                    ([], {}),
                )
            )
        )

        # combine kwargs
        self.assertEqual(
            ([], {'first': 'one', 'second': 'two'}),
            args.combine_args(
                funcdef, (
                    ([], {}),
                    ([], {'first': 'one', 'second': 'two'}),
                )
            )
        )

        # combine mixed args
        self.assertEqual(
            ([], {'first': 'one', 'second': 'two'}),
            args.combine_args(
                funcdef, (
                    (['one'], {}),
                    ([], {'second': 'two'}),
                )
            )
        )

        # override kwargs
        self.assertEqual(
            ([], {'first': 'two'}),
            args.combine_args(
                funcdef, (
                    ([], {'first': 'one'}),
                    ([], {'first': 'two'}),
                ),
                allow_override=True
            )
        )

        # override args
        self.assertEqual(
            ([], {'first': 'two', 'second': 'three'}),
            args.combine_args(
                funcdef, (
                    (['one', 'three'], {}),
                    (['two'], {}),
                ),
                allow_override=True
            )
        )

        # can't override args
        self.assertRaises(exception.ClientSideError, args.combine_args,
                          funcdef,
                          ((['one'], {}), (['two'], {})))

        # can't override kwargs
        self.assertRaises(exception.ClientSideError, args.combine_args,
                          funcdef,
                          (([], {'first': 'one'}), ([], {'first': 'two'})))

    def test_get_args(self):
        @functions.signature(str, str, int, atypes.ArrayType(int),
                             types.listtype, body=NestedObj)
        def myfunc(self, first, second, third, foo, nested):
            pass
        funcdef = functions.FunctionDefinition.get(myfunc)
        params = multidict.MultiDict(
            foo='0,1, 2, three',
            second='2'
        )
        mimetype = 'application/json'
        body = b'{"o": {"id": 1234, "name": "an object"}}'
        fromargs = ['one']
        fromkwargs = {'third': '1'}

        newargs, newkwargs = args.get_args(funcdef, fromargs, fromkwargs,
                                           params, body, mimetype)
        self.assertEqual([], newargs)
        n = newkwargs.pop('nested')
        self.assertEqual({
            'first': 'one',
            'foo': ['0', '1', '2', 'three'],
            'second': 2,
            'third': [1]},
            newkwargs
        )
        self.assertEqual(1234, n.o.id)
        self.assertEqual('an object', n.o.name)

        # check_arguments missing mandatory argument 'second'
        params = multidict.MultiDict(
            foo='0,1, 2, three',
        )
        self.assertRaises(exception.MissingArgument, args.get_args,
                          funcdef, fromargs, fromkwargs,
                          params, body, mimetype)
