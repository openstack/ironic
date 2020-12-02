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

from oslo_utils import uuidutils

from ironic.common import args
from ironic.common import exception
from ironic.tests import base


class ArgsDecorated(object):

    @args.validate(one=args.string,
                   two=args.boolean,
                   three=args.uuid,
                   four=args.uuid_or_name)
    def method(self, one, two, three, four):
        return one, two, three, four

    @args.validate(one=args.string)
    def needs_string(self, one):
        return one

    @args.validate(one=args.boolean)
    def needs_boolean(self, one):
        return one

    @args.validate(one=args.uuid)
    def needs_uuid(self, one):
        return one

    @args.validate(one=args.name)
    def needs_name(self, one):
        return one

    @args.validate(one=args.uuid_or_name)
    def needs_uuid_or_name(self, one):
        return one

    @args.validate(one=args.string_list)
    def needs_string_list(self, one):
        return one

    @args.validate(one=args.integer)
    def needs_integer(self, one):
        return one

    @args.validate(one=args.mac_address)
    def needs_mac_address(self, one):
        return one

    @args.validate(one=args.schema({
        'type': 'array',
        'items': {
            'type': 'object',
            'properties': {
                'name': {'type': 'string'},
                'count': {'type': 'integer', 'minimum': 0},
            },
            'additionalProperties': False,
            'required': ['name'],
        }
    }))
    def needs_schema(self, one):
        return one

    @args.validate(one=args.string, two=args.string, the_rest=args.schema({
        'type': 'object',
        'properties': {
            'three': {'type': 'string'},
            'four': {'type': 'string', 'maxLength': 4},
            'five': {'type': 'string'},
        },
        'additionalProperties': False,
        'required': ['three']
    }))
    def needs_schema_kwargs(self, one, two, **the_rest):
        return one, two, the_rest

    @args.validate(one=args.string, two=args.string, the_rest=args.schema({
        'type': 'array',
        'items': {'type': 'string'}
    }))
    def needs_schema_args(self, one, two=None, *the_rest):
        return one, two, the_rest

    @args.validate(one=args.string, two=args.string, args=args.schema({
        'type': 'array',
        'items': {'type': 'string'}
    }), kwargs=args.schema({
        'type': 'object',
        'properties': {
            'four': {'type': 'string'},
        },
    }))
    def needs_schema_mixed(self, one, two=None, *args, **kwargs):
        return one, two, args, kwargs

    @args.validate(one=args.string)
    def needs_mixed_unvalidated(self, one, two=None, *args, **kwargs):
        return one, two, args, kwargs

    @args.validate(body=args.patch)
    def patch(self, body):
        return body


class BaseTest(base.TestCase):

    def setUp(self):
        super(BaseTest, self).setUp()
        self.decorated = ArgsDecorated()


class ValidateDecoratorTest(BaseTest):

    def test_decorated_args(self):
        uuid = uuidutils.generate_uuid()
        self.assertEqual((
            'a',
            True,
            uuid,
            'a_name',
        ), self.decorated.method(
            'a',
            True,
            uuid,
            'a_name',
        ))

    def test_decorated_kwargs(self):
        uuid = uuidutils.generate_uuid()
        self.assertEqual((
            'a',
            True,
            uuid,
            'a_name',
        ), self.decorated.method(
            one='a',
            two=True,
            three=uuid,
            four='a_name',
        ))

    def test_decorated_args_kwargs(self):
        uuid = uuidutils.generate_uuid()
        self.assertEqual((
            'a',
            True,
            uuid,
            'a_name',
        ), self.decorated.method(
            'a',
            True,
            uuid,
            four='a_name',
        ))

    def test_decorated_function(self):

        @args.validate(one=args.string,
                       two=args.boolean,
                       three=args.uuid,
                       four=args.uuid_or_name)
        def func(one, two, three, four):
            return one, two, three, four

        uuid = uuidutils.generate_uuid()
        self.assertEqual((
            'a',
            True,
            uuid,
            'a_name',
        ), func(
            'a',
            'yes',
            uuid,
            four='a_name',
        ))

    def test_unexpected_args(self):
        uuid = uuidutils.generate_uuid()
        e = self.assertRaises(
            exception.InvalidParameterValue,
            self.decorated.method,
            one='a',
            two=True,
            three=uuid,
            four='a_name',
            five='5',
            six=6
        )
        self.assertIn('Unexpected arguments: ', str(e))
        self.assertIn('five', str(e))
        self.assertIn('six', str(e))

    def test_string(self):
        self.assertEqual('foo', self.decorated.needs_string('foo'))
        self.assertIsNone(self.decorated.needs_string(None))
        self.assertRaises(exception.InvalidParameterValue,
                          self.decorated.needs_string, 123)

    def test_boolean(self):
        self.assertTrue(self.decorated.needs_boolean('yes'))
        self.assertTrue(self.decorated.needs_boolean('true'))
        self.assertTrue(self.decorated.needs_boolean(True))

        self.assertFalse(self.decorated.needs_boolean('no'))
        self.assertFalse(self.decorated.needs_boolean('false'))
        self.assertFalse(self.decorated.needs_boolean(False))

        self.assertIsNone(self.decorated.needs_boolean(None))
        self.assertRaises(exception.InvalidParameterValue,
                          self.decorated.needs_boolean,
                          'yeah nah yeah nah')

    def test_uuid(self):
        uuid = uuidutils.generate_uuid()
        self.assertEqual(uuid, self.decorated.needs_uuid(uuid))
        self.assertIsNone(self.decorated.needs_uuid(None))
        self.assertRaises(exception.InvalidParameterValue,
                          self.decorated.needs_uuid, uuid + 'XXX')

    def test_name(self):
        self.assertEqual('foo', self.decorated.needs_name('foo'))
        self.assertIsNone(self.decorated.needs_name(None))
        self.assertRaises(exception.InvalidParameterValue,
                          self.decorated.needs_name, 'I am a name')

    def test_uuid_or_name(self):
        uuid = uuidutils.generate_uuid()
        self.assertEqual(uuid, self.decorated.needs_uuid_or_name(uuid))
        self.assertEqual('foo', self.decorated.needs_uuid_or_name('foo'))
        self.assertIsNone(self.decorated.needs_uuid_or_name(None))
        self.assertRaises(exception.InvalidParameterValue,
                          self.decorated.needs_uuid_or_name,
                          'I am a name')

    def test_string_list(self):
        self.assertEqual([
            'foo', 'bar', 'baz'
        ], self.decorated.needs_string_list('foo, bar ,bAZ'))
        self.assertIsNone(self.decorated.needs_name(None))
        self.assertRaises(exception.InvalidParameterValue,
                          self.decorated.needs_name, True)

    def test_integer(self):
        self.assertEqual(123, self.decorated.needs_integer(123))
        self.assertIsNone(self.decorated.needs_integer(None))
        self.assertRaises(exception.InvalidParameterValue,
                          self.decorated.needs_integer,
                          'more than a number')

    def test_mac_address(self):
        self.assertEqual('02:ce:20:50:68:6f',
                         self.decorated.needs_mac_address('02:cE:20:50:68:6F'))
        self.assertIsNone(self.decorated.needs_mac_address(None))
        self.assertRaises(exception.InvalidParameterValue,
                          self.decorated.needs_mac_address,
                          'big:mac')

    def test_mixed_unvalidated(self):
        # valid
        self.assertEqual((
            'one', 'two', ('three', 'four', 'five'), {}
        ), self.decorated.needs_mixed_unvalidated(
            'one', 'two', 'three', 'four', 'five',
        ))
        self.assertEqual((
            'one', 'two', ('three',), {'four': 'four', 'five': 'five'}
        ), self.decorated.needs_mixed_unvalidated(
            'one', 'two', 'three', four='four', five='five',
        ))
        self.assertEqual((
            'one', 'two', (), {}
        ), self.decorated.needs_mixed_unvalidated(
            'one', 'two',
        ))
        self.assertEqual((
            'one', None, (), {}
        ), self.decorated.needs_mixed_unvalidated(
            'one',
        ))

        # wrong type in one
        self.assertRaises(exception.InvalidParameterValue,
                          self.decorated.needs_mixed_unvalidated, 1)

    def test_mandatory(self):

        @args.validate(foo=args.string)
        def doit(foo):
            return foo

        @args.validate(foo=args.string)
        def doit_maybe(foo='baz'):
            return foo

        # valid
        self.assertEqual('bar', doit('bar'))

        # invalid, argument not provided
        self.assertRaises(exception.InvalidParameterValue, doit)

        # valid, not mandatory
        self.assertEqual('baz', doit_maybe())

    def test_or(self):

        @args.validate(foo=args.or_valid(
            args.string,
            args.integer,
            args.boolean
        ))
        def doit(foo):
            return foo

        # valid
        self.assertEqual('bar', doit('bar'))
        self.assertEqual(1, doit(1))
        self.assertEqual(True, doit(True))

        # invalid, wrong type
        self.assertRaises(exception.InvalidParameterValue, doit, {})

    def test_and(self):

        @args.validate(foo=args.and_valid(
            args.string,
            args.name
        ))
        def doit(foo):
            return foo

        # valid
        self.assertEqual('bar', doit('bar'))

        # invalid, not a string
        self.assertRaises(exception.InvalidParameterValue, doit, 2)

        # invalid, not a name
        self.assertRaises(exception.InvalidParameterValue, doit, 'not a name')


class ValidateSchemaTest(BaseTest):

    def test_schema(self):
        valid = [
            {'name': 'zero'},
            {'name': 'one', 'count': 1},
            {'name': 'two', 'count': 2}
        ]
        invalid_count = [
            {'name': 'neg', 'count': -1},
            {'name': 'one', 'count': 1},
            {'name': 'two', 'count': 2}
        ]
        invalid_root = {}
        self.assertEqual(valid, self.decorated.needs_schema(valid))
        self.assertRaises(exception.InvalidParameterValue,
                          self.decorated.needs_schema,
                          invalid_count)
        self.assertRaises(exception.InvalidParameterValue,
                          self.decorated.needs_schema,
                          invalid_root)

    def test_schema_needs_kwargs(self):
        # valid
        self.assertEqual((
            'one', 'two', {
                'three': 'three',
                'four': 'four',
                'five': 'five',
            }
        ), self.decorated.needs_schema_kwargs(
            one='one',
            two='two',
            three='three',
            four='four',
            five='five',
        ))
        self.assertEqual((
            'one', 'two', {
                'three': 'three',
            }
        ), self.decorated.needs_schema_kwargs(
            one='one',
            two='two',
            three='three',
        ))
        self.assertEqual((
            'one', 'two', {}
        ), self.decorated.needs_schema_kwargs(
            one='one',
            two='two',
        ))

        # missing mandatory 'three'
        self.assertRaises(exception.InvalidParameterValue,
                          self.decorated.needs_schema_kwargs,
                          one='one', two='two', four='four', five='five')

        # 'four' value exceeds length
        self.assertRaises(exception.InvalidParameterValue,
                          self.decorated.needs_schema_kwargs,
                          one='one', two='two', three='three',
                          four='beforefore', five='five')

    def test_schema_needs_args(self):
        # valid
        self.assertEqual((
            'one', 'two', ('three', 'four', 'five')
        ), self.decorated.needs_schema_args(
            'one', 'two', 'three', 'four', 'five',
        ))
        self.assertEqual((
            'one', 'two', ('three',)
        ), self.decorated.needs_schema_args(
            'one', 'two', 'three',
        ))
        self.assertEqual((
            'one', 'two', ()
        ), self.decorated.needs_schema_args(
            'one', 'two',
        ))
        self.assertEqual((
            'one', None, ()
        ), self.decorated.needs_schema_args(
            'one',
        ))

        # failed, non string *the_rest value
        self.assertRaises(exception.InvalidParameterValue,
                          self.decorated.needs_schema_args,
                          'one', 'two', 'three', 4, False)

    def test_schema_needs_mixed(self):
        # valid
        self.assertEqual((
            'one', 'two', ('three', 'four', 'five'), {}
        ), self.decorated.needs_schema_mixed(
            'one', 'two', 'three', 'four', 'five',
        ))
        self.assertEqual((
            'one', 'two', ('three', ), {'four': 'four'}
        ), self.decorated.needs_schema_mixed(
            'one', 'two', 'three', four='four',
        ))
        self.assertEqual((
            'one', 'two', (), {'four': 'four'}
        ), self.decorated.needs_schema_mixed(
            'one', 'two', four='four',
        ))
        self.assertEqual((
            'one', None, (), {}
        ), self.decorated.needs_schema_mixed(
            'one',
        ))

        # wrong type in *args
        self.assertRaises(exception.InvalidParameterValue,
                          self.decorated.needs_schema_mixed,
                          'one', 'two', 3, four='four')
        # wrong type in *kwargs
        self.assertRaises(exception.InvalidParameterValue,
                          self.decorated.needs_schema_mixed,
                          'one', 'two', 'three', four=4)


class ValidatePatchSchemaTest(BaseTest):

    def test_patch(self):
        data = [{
            'path': '/foo',
            'op': 'replace',
            'value': 'bar'
        }, {
            'path': '/foo/bar',
            'op': 'add',
            'value': True
        }, {
            'path': '/foo/bar/baz',
            'op': 'remove',
            'value': 123
        }]

        self.assertEqual(
            data,
            self.decorated.patch(data)
        )

    def assertValidationFailed(self, data, error_snippets=None):
        e = self.assertRaises(exception.InvalidParameterValue,
                              self.decorated.patch, data)
        if error_snippets:
            for s in error_snippets:
                self.assertIn(s, str(e))

    def test_patch_validation_failed(self):
        self.assertValidationFailed(
            {},
            ["Schema error for body:",
             "{} is not of type 'array'"])
        self.assertValidationFailed(
            [{
                'path': '/foo/bar/baz',
                'op': 'fribble',
                'value': 123
            }],
            ["Schema error for body:",
             "'fribble' is not one of ['add', 'replace', 'remove']"])
        self.assertValidationFailed(
            [{
                'path': '/',
                'op': 'add',
                'value': 123
            }],
            ["Schema error for body:",
             "'/' does not match"])
        self.assertValidationFailed(
            [{
                'path': 'foo/',
                'op': 'add',
                'value': 123
            }],
            ["Schema error for body:",
             "'foo/' does not match"])
        self.assertValidationFailed(
            [{
                'path': '/foo bar',
                'op': 'add',
                'value': 123
            }],
            ["Schema error for body:",
             "'/foo bar' does not match"])


class ValidateDictTest(BaseTest):

    def test_dict_valid(self):
        uuid = uuidutils.generate_uuid()

        @args.validate(foo=args.dict_valid(
            bar=args.uuid
        ))
        def doit(foo):
            return foo

        # validate passes
        doit(foo={'bar': uuid})

        # tolerate other keys
        doit(foo={'bar': uuid, 'baz': 'baz'})

        # key missing
        doit({})

        # value fails validation
        e = self.assertRaises(exception.InvalidParameterValue,
                              doit, {'bar': uuid + 'XXX'})
        self.assertIn('Expected UUID for bar:', str(e))

        # not a dict
        e = self.assertRaises(exception.InvalidParameterValue,
                              doit, 'asdf')
        self.assertIn("Expected types <class 'dict'> for foo: asdf", str(e))

    def test_dict_valid_colon_key_name(self):
        uuid = uuidutils.generate_uuid()

        @args.validate(foo=args.dict_valid(**{
            'bar:baz': args.uuid
        }
        ))
        def doit(foo):
            return foo

        # validate passes
        doit(foo={'bar:baz': uuid})

        # value fails validation
        e = self.assertRaises(exception.InvalidParameterValue,
                              doit, {'bar:baz': uuid + 'XXX'})
        self.assertIn('Expected UUID for bar:', str(e))


class ValidateTypesTest(BaseTest):

    def test_types(self):

        @args.validate(foo=args.types(None, dict, str))
        def doit(foo):
            return foo

        # valid None
        self.assertIsNone(doit(None))

        # valid dict
        self.assertEqual({'foo': 'bar'}, doit({'foo': 'bar'}))

        # valid string
        self.assertEqual('foo', doit('foo'))

        # invalid integer
        e = self.assertRaises(exception.InvalidParameterValue,
                              doit, 123)
        self.assertIn("Expected types "
                      "<class 'NoneType'>, <class 'dict'>, <class 'str'> "
                      "for foo: 123", str(e))
