#    Copyright 2013 IBM Corp.
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

import contextlib
import datetime
import gettext

import iso8601
import netaddr
from oslo_context import context
from oslo_utils import timeutils
import six

from ironic.common import exception
from ironic.objects import base
from ironic.objects import utils
from ironic.tests import base as test_base

gettext.install('ironic')


class MyObj(base.IronicObject):
    VERSION = '1.5'

    fields = {'foo': int,
              'bar': str,
              'missing': str,
              }

    def obj_load_attr(self, attrname):
        setattr(self, attrname, 'loaded!')

    @base.remotable_classmethod
    def query(cls, context):
        obj = cls(context)
        obj.foo = 1
        obj.bar = 'bar'
        obj.obj_reset_changes()
        return obj

    @base.remotable
    def marco(self, context):
        return 'polo'

    @base.remotable
    def update_test(self, context):
        if context.tenant == 'alternate':
            self.bar = 'alternate-context'
        else:
            self.bar = 'updated'

    @base.remotable
    def save(self, context):
        self.obj_reset_changes()

    @base.remotable
    def refresh(self, context):
        self.foo = 321
        self.bar = 'refreshed'
        self.obj_reset_changes()

    @base.remotable
    def modify_save_modify(self, context):
        self.bar = 'meow'
        self.save()
        self.foo = 42


class MyObj2(object):
    @classmethod
    def obj_name(cls):
        return 'MyObj'

    @base.remotable_classmethod
    def get(cls, *args, **kwargs):
        pass


class TestSubclassedObject(MyObj):
    fields = {'new_field': str}


class TestMetaclass(test_base.TestCase):
    def test_obj_tracking(self):

        @six.add_metaclass(base.IronicObjectMetaclass)
        class NewBaseClass(object):
            fields = {}

            @classmethod
            def obj_name(cls):
                return cls.__name__

        class Test1(NewBaseClass):
            @staticmethod
            def obj_name():
                return 'fake1'

        class Test2(NewBaseClass):
            pass

        class Test2v2(NewBaseClass):
            @staticmethod
            def obj_name():
                return 'Test2'

        expected = {'fake1': [Test1], 'Test2': [Test2, Test2v2]}

        self.assertEqual(expected, NewBaseClass._obj_classes)
        # The following should work, also.
        self.assertEqual(expected, Test1._obj_classes)
        self.assertEqual(expected, Test2._obj_classes)


class TestUtils(test_base.TestCase):

    def test_datetime_or_none(self):
        naive_dt = datetime.datetime.now()
        dt = timeutils.parse_isotime(timeutils.isotime(naive_dt))
        self.assertEqual(utils.datetime_or_none(dt), dt)
        self.assertEqual(utils.datetime_or_none(dt),
                         naive_dt.replace(tzinfo=iso8601.iso8601.Utc(),
                                          microsecond=0))
        self.assertIsNone(utils.datetime_or_none(None))
        self.assertRaises(ValueError, utils.datetime_or_none, 'foo')

    def test_datetime_or_str_or_none(self):
        dts = timeutils.isotime()
        dt = timeutils.parse_isotime(dts)
        self.assertEqual(utils.datetime_or_str_or_none(dt), dt)
        self.assertIsNone(utils.datetime_or_str_or_none(None))
        self.assertEqual(utils.datetime_or_str_or_none(dts), dt)
        self.assertRaises(ValueError, utils.datetime_or_str_or_none, 'foo')

    def test_int_or_none(self):
        self.assertEqual(utils.int_or_none(1), 1)
        self.assertEqual(utils.int_or_none('1'), 1)
        self.assertIsNone(utils.int_or_none(None))
        self.assertRaises(ValueError, utils.int_or_none, 'foo')

    def test_str_or_none(self):
        class Obj(object):
            pass
        self.assertEqual(utils.str_or_none('foo'), 'foo')
        self.assertEqual(utils.str_or_none(1), '1')
        self.assertIsNone(utils.str_or_none(None))

    def test_ip_or_none(self):
        ip4 = netaddr.IPAddress('1.2.3.4', 4)
        ip6 = netaddr.IPAddress('1::2', 6)
        self.assertEqual(utils.ip_or_none(4)('1.2.3.4'), ip4)
        self.assertEqual(utils.ip_or_none(6)('1::2'), ip6)
        self.assertIsNone(utils.ip_or_none(4)(None))
        self.assertIsNone(utils.ip_or_none(6)(None))
        self.assertRaises(netaddr.AddrFormatError, utils.ip_or_none(4), 'foo')
        self.assertRaises(netaddr.AddrFormatError, utils.ip_or_none(6), 'foo')

    def test_dt_serializer(self):
        class Obj(object):
            foo = utils.dt_serializer('bar')

        obj = Obj()
        obj.bar = timeutils.parse_isotime('1955-11-05T00:00:00Z')
        self.assertEqual('1955-11-05T00:00:00Z', obj.foo())
        obj.bar = None
        self.assertIsNone(obj.foo())
        obj.bar = 'foo'
        self.assertRaises(AttributeError, obj.foo)

    def test_dt_deserializer(self):
        dt = timeutils.parse_isotime('1955-11-05T00:00:00Z')
        self.assertEqual(utils.dt_deserializer(None, timeutils.isotime(dt)),
                         dt)
        self.assertIsNone(utils.dt_deserializer(None, None))
        self.assertRaises(ValueError, utils.dt_deserializer, None, 'foo')

    def test_obj_to_primitive_list(self):
        class MyList(base.ObjectListBase, base.IronicObject):
            pass
        mylist = MyList(self.context)
        mylist.objects = [1, 2, 3]
        self.assertEqual([1, 2, 3], base.obj_to_primitive(mylist))

    def test_obj_to_primitive_dict(self):
        myobj = MyObj(self.context)
        myobj.foo = 1
        myobj.bar = 'foo'
        self.assertEqual({'foo': 1, 'bar': 'foo'},
                         base.obj_to_primitive(myobj))

    def test_obj_to_primitive_recursive(self):
        class MyList(base.ObjectListBase, base.IronicObject):
            pass

        mylist = MyList(self.context)
        mylist.objects = [MyObj(self.context), MyObj(self.context)]
        for i, value in enumerate(mylist):
            value.foo = i
        self.assertEqual([{'foo': 0}, {'foo': 1}],
                         base.obj_to_primitive(mylist))


class _BaseTestCase(test_base.TestCase):
    def setUp(self):
        super(_BaseTestCase, self).setUp()
        self.remote_object_calls = list()


class _LocalTest(_BaseTestCase):
    def setUp(self):
        super(_LocalTest, self).setUp()
        # Just in case
        base.IronicObject.indirection_api = None

    def assertRemotes(self):
        self.assertEqual([], self.remote_object_calls)


@contextlib.contextmanager
def things_temporarily_local():
    # Temporarily go non-remote so the conductor handles
    # this request directly
    _api = base.IronicObject.indirection_api
    base.IronicObject.indirection_api = None
    yield
    base.IronicObject.indirection_api = _api


class _TestObject(object):
    def test_hydration_type_error(self):
        primitive = {'ironic_object.name': 'MyObj',
                     'ironic_object.namespace': 'ironic',
                     'ironic_object.version': '1.5',
                     'ironic_object.data': {'foo': 'a'}}
        self.assertRaises(ValueError, MyObj.obj_from_primitive, primitive)

    def test_hydration(self):
        primitive = {'ironic_object.name': 'MyObj',
                     'ironic_object.namespace': 'ironic',
                     'ironic_object.version': '1.5',
                     'ironic_object.data': {'foo': 1}}
        obj = MyObj.obj_from_primitive(primitive)
        self.assertEqual(1, obj.foo)

    def test_hydration_bad_ns(self):
        primitive = {'ironic_object.name': 'MyObj',
                     'ironic_object.namespace': 'foo',
                     'ironic_object.version': '1.5',
                     'ironic_object.data': {'foo': 1}}
        self.assertRaises(exception.UnsupportedObjectError,
                          MyObj.obj_from_primitive, primitive)

    def test_dehydration(self):
        expected = {'ironic_object.name': 'MyObj',
                    'ironic_object.namespace': 'ironic',
                    'ironic_object.version': '1.5',
                    'ironic_object.data': {'foo': 1}}
        obj = MyObj(self.context)
        obj.foo = 1
        obj.obj_reset_changes()
        self.assertEqual(expected, obj.obj_to_primitive())

    def test_get_updates(self):
        obj = MyObj(self.context)
        self.assertEqual({}, obj.obj_get_changes())
        obj.foo = 123
        self.assertEqual({'foo': 123}, obj.obj_get_changes())
        obj.bar = 'test'
        self.assertEqual({'foo': 123, 'bar': 'test'}, obj.obj_get_changes())
        obj.obj_reset_changes()
        self.assertEqual({}, obj.obj_get_changes())

    def test_object_property(self):
        obj = MyObj(self.context, foo=1)
        self.assertEqual(1, obj.foo)

    def test_object_property_type_error(self):
        obj = MyObj(self.context)

        def fail():
            obj.foo = 'a'
        self.assertRaises(ValueError, fail)

    def test_object_dict_syntax(self):
        obj = MyObj(self.context)
        obj.foo = 123
        obj.bar = 'bar'
        self.assertEqual(123, obj['foo'])
        self.assertEqual([('bar', 'bar'), ('foo', 123)],
                         sorted(obj.items(), key=lambda x: x[0]))
        self.assertEqual([('bar', 'bar'), ('foo', 123)],
                         sorted(list(obj.iteritems()), key=lambda x: x[0]))

    def test_load(self):
        obj = MyObj(self.context)
        self.assertEqual('loaded!', obj.bar)

    def test_load_in_base(self):
        class Foo(base.IronicObject):
            fields = {'foobar': int}
        obj = Foo(self.context)
        # NOTE(danms): Can't use assertRaisesRegexp() because of py26
        raised = False
        try:
            obj.foobar
        except NotImplementedError as ex:
            raised = True
        self.assertTrue(raised)
        self.assertTrue('foobar' in str(ex))

    def test_loaded_in_primitive(self):
        obj = MyObj(self.context)
        obj.foo = 1
        obj.obj_reset_changes()
        self.assertEqual('loaded!', obj.bar)
        expected = {'ironic_object.name': 'MyObj',
                    'ironic_object.namespace': 'ironic',
                    'ironic_object.version': '1.5',
                    'ironic_object.changes': ['bar'],
                    'ironic_object.data': {'foo': 1,
                                         'bar': 'loaded!'}}
        self.assertEqual(expected, obj.obj_to_primitive())

    def test_changes_in_primitive(self):
        obj = MyObj(self.context)
        obj.foo = 123
        self.assertEqual(set(['foo']), obj.obj_what_changed())
        primitive = obj.obj_to_primitive()
        self.assertTrue('ironic_object.changes' in primitive)
        obj2 = MyObj.obj_from_primitive(primitive)
        self.assertEqual(set(['foo']), obj2.obj_what_changed())
        obj2.obj_reset_changes()
        self.assertEqual(set(), obj2.obj_what_changed())

    def test_unknown_objtype(self):
        self.assertRaises(exception.UnsupportedObjectError,
                          base.IronicObject.obj_class_from_name, 'foo', '1.0')

    def test_with_alternate_context(self):
        ctxt1 = context.RequestContext('foo', 'foo')
        ctxt2 = context.RequestContext('bar', tenant='alternate')
        obj = MyObj.query(ctxt1)
        obj.update_test(ctxt2)
        self.assertEqual('alternate-context', obj.bar)
        self.assertRemotes()

    def test_orphaned_object(self):
        obj = MyObj.query(self.context)
        obj._context = None
        self.assertRaises(exception.OrphanedObjectError,
                          obj.update_test)
        self.assertRemotes()

    def test_changed_1(self):
        obj = MyObj.query(self.context)
        obj.foo = 123
        self.assertEqual(set(['foo']), obj.obj_what_changed())
        obj.update_test(self.context)
        self.assertEqual(set(['foo', 'bar']), obj.obj_what_changed())
        self.assertEqual(123, obj.foo)
        self.assertRemotes()

    def test_changed_2(self):
        obj = MyObj.query(self.context)
        obj.foo = 123
        self.assertEqual(set(['foo']), obj.obj_what_changed())
        obj.save()
        self.assertEqual(set([]), obj.obj_what_changed())
        self.assertEqual(123, obj.foo)
        self.assertRemotes()

    def test_changed_3(self):
        obj = MyObj.query(self.context)
        obj.foo = 123
        self.assertEqual(set(['foo']), obj.obj_what_changed())
        obj.refresh()
        self.assertEqual(set([]), obj.obj_what_changed())
        self.assertEqual(321, obj.foo)
        self.assertEqual('refreshed', obj.bar)
        self.assertRemotes()

    def test_changed_4(self):
        obj = MyObj.query(self.context)
        obj.bar = 'something'
        self.assertEqual(set(['bar']), obj.obj_what_changed())
        obj.modify_save_modify(self.context)
        self.assertEqual(set(['foo']), obj.obj_what_changed())
        self.assertEqual(42, obj.foo)
        self.assertEqual('meow', obj.bar)
        self.assertRemotes()

    def test_static_result(self):
        obj = MyObj.query(self.context)
        self.assertEqual('bar', obj.bar)
        result = obj.marco()
        self.assertEqual('polo', result)
        self.assertRemotes()

    def test_updates(self):
        obj = MyObj.query(self.context)
        self.assertEqual(1, obj.foo)
        obj.update_test()
        self.assertEqual('updated', obj.bar)
        self.assertRemotes()

    def test_base_attributes(self):
        dt = datetime.datetime(1955, 11, 5)
        obj = MyObj(self.context)
        obj.created_at = dt
        obj.updated_at = dt
        expected = {'ironic_object.name': 'MyObj',
                    'ironic_object.namespace': 'ironic',
                    'ironic_object.version': '1.5',
                    'ironic_object.changes':
                        ['created_at', 'updated_at'],
                    'ironic_object.data':
                        {'created_at': timeutils.isotime(dt),
                         'updated_at': timeutils.isotime(dt),
                         }
                    }
        actual = obj.obj_to_primitive()
        # ironic_object.changes is built from a set and order is undefined
        self.assertEqual(sorted(expected['ironic_object.changes']),
                         sorted(actual['ironic_object.changes']))
        del expected['ironic_object.changes'], actual['ironic_object.changes']
        self.assertEqual(expected, actual)

    def test_contains(self):
        obj = MyObj(self.context)
        self.assertFalse('foo' in obj)
        obj.foo = 1
        self.assertTrue('foo' in obj)
        self.assertFalse('does_not_exist' in obj)

    def test_obj_attr_is_set(self):
        obj = MyObj(self.context, foo=1)
        self.assertTrue(obj.obj_attr_is_set('foo'))
        self.assertFalse(obj.obj_attr_is_set('bar'))
        self.assertRaises(AttributeError, obj.obj_attr_is_set, 'bang')

    def test_get(self):
        obj = MyObj(self.context, foo=1)
        # Foo has value, should not get the default
        self.assertEqual(obj.get('foo', 2), 1)
        # Foo has value, should return the value without error
        self.assertEqual(obj.get('foo'), 1)
        # Bar is not loaded, so we should get the default
        self.assertEqual(obj.get('bar', 'not-loaded'), 'not-loaded')
        # Bar without a default should lazy-load
        self.assertEqual(obj.get('bar'), 'loaded!')
        # Bar now has a default, but loaded value should be returned
        self.assertEqual(obj.get('bar', 'not-loaded'), 'loaded!')
        # Invalid attribute should raise AttributeError
        self.assertRaises(AttributeError, obj.get, 'nothing')
        # ...even with a default
        self.assertRaises(AttributeError, obj.get, 'nothing', 3)

    def test_object_inheritance(self):
        base_fields = base.IronicObject.fields.keys()
        myobj_fields = ['foo', 'bar', 'missing'] + base_fields
        myobj3_fields = ['new_field']
        self.assertTrue(issubclass(TestSubclassedObject, MyObj))
        self.assertEqual(len(myobj_fields), len(MyObj.fields))
        self.assertEqual(set(myobj_fields), set(MyObj.fields.keys()))
        self.assertEqual(len(myobj_fields) + len(myobj3_fields),
                         len(TestSubclassedObject.fields))
        self.assertEqual(set(myobj_fields) | set(myobj3_fields),
                         set(TestSubclassedObject.fields.keys()))

    def test_get_changes(self):
        obj = MyObj(self.context)
        self.assertEqual({}, obj.obj_get_changes())
        obj.foo = 123
        self.assertEqual({'foo': 123}, obj.obj_get_changes())
        obj.bar = 'test'
        self.assertEqual({'foo': 123, 'bar': 'test'}, obj.obj_get_changes())
        obj.obj_reset_changes()
        self.assertEqual({}, obj.obj_get_changes())

    def test_obj_fields(self):
        class TestObj(base.IronicObject):
            fields = {'foo': int}
            obj_extra_fields = ['bar']

            @property
            def bar(self):
                return 'this is bar'

        obj = TestObj(self.context)
        self.assertEqual(set(['created_at', 'updated_at', 'foo', 'bar']),
                         set(obj.obj_fields))

    def test_obj_constructor(self):
        obj = MyObj(self.context, foo=123, bar='abc')
        self.assertEqual(123, obj.foo)
        self.assertEqual('abc', obj.bar)
        self.assertEqual(set(['foo', 'bar']), obj.obj_what_changed())


class TestObject(_LocalTest, _TestObject):
    pass


class TestObjectListBase(test_base.TestCase):

    def test_list_like_operations(self):
        class Foo(base.ObjectListBase, base.IronicObject):
            pass

        objlist = Foo(self.context)
        objlist._context = 'foo'
        objlist.objects = [1, 2, 3]
        self.assertEqual(list(objlist), objlist.objects)
        self.assertEqual(3, len(objlist))
        self.assertIn(2, objlist)
        self.assertEqual([1], list(objlist[:1]))
        self.assertEqual('foo', objlist[:1]._context)
        self.assertEqual(3, objlist[2])
        self.assertEqual(1, objlist.count(1))
        self.assertEqual(1, objlist.index(2))

    def test_serialization(self):
        class Foo(base.ObjectListBase, base.IronicObject):
            pass

        class Bar(base.IronicObject):
            fields = {'foo': str}

        obj = Foo(self.context)
        obj.objects = []
        for i in 'abc':
            bar = Bar(self.context)
            bar.foo = i
            obj.objects.append(bar)

        obj2 = base.IronicObject.obj_from_primitive(obj.obj_to_primitive())
        self.assertFalse(obj is obj2)
        self.assertEqual([x.foo for x in obj],
                         [y.foo for y in obj2])

    def _test_object_list_version_mappings(self, list_obj_class):
        # Figure out what sort of object this list is for
        list_field = list_obj_class.fields['objects']
        item_obj_field = list_field._type._element_type
        item_obj_name = item_obj_field._type._obj_name

        # Look through all object classes of this type and make sure that
        # the versions we find are covered by the parent list class
        for item_class in base.IronicObject._obj_classes[item_obj_name]:
            self.assertIn(
                item_class.VERSION,
                list_obj_class.child_versions.values())

    def test_object_version_mappings(self):
        # Find all object list classes and make sure that they at least handle
        # all the current object versions
        for obj_classes in base.IronicObject._obj_classes.values():
            for obj_class in obj_classes:
                if issubclass(obj_class, base.ObjectListBase):
                    self._test_object_list_version_mappings(obj_class)

    def test_list_changes(self):
        class Foo(base.ObjectListBase, base.IronicObject):
            pass

        class Bar(base.IronicObject):
            fields = {'foo': str}

        obj = Foo(self.context, objects=[])
        self.assertEqual(set(['objects']), obj.obj_what_changed())
        obj.objects.append(Bar(self.context, foo='test'))
        self.assertEqual(set(['objects']), obj.obj_what_changed())
        obj.obj_reset_changes()
        # This should still look dirty because the child is dirty
        self.assertEqual(set(['objects']), obj.obj_what_changed())
        obj.objects[0].obj_reset_changes()
        # This should now look clean because the child is clean
        self.assertEqual(set(), obj.obj_what_changed())


class TestObjectSerializer(test_base.TestCase):

    def test_serialize_entity_primitive(self):
        ser = base.IronicObjectSerializer()
        for thing in (1, 'foo', [1, 2], {'foo': 'bar'}):
            self.assertEqual(thing, ser.serialize_entity(None, thing))

    def test_deserialize_entity_primitive(self):
        ser = base.IronicObjectSerializer()
        for thing in (1, 'foo', [1, 2], {'foo': 'bar'}):
            self.assertEqual(thing, ser.deserialize_entity(None, thing))

    def test_object_serialization(self):
        ser = base.IronicObjectSerializer()
        obj = MyObj(self.context)
        primitive = ser.serialize_entity(self.context, obj)
        self.assertTrue('ironic_object.name' in primitive)
        obj2 = ser.deserialize_entity(self.context, primitive)
        self.assertIsInstance(obj2, MyObj)
        self.assertEqual(self.context, obj2._context)

    def test_object_serialization_iterables(self):
        ser = base.IronicObjectSerializer()
        obj = MyObj(self.context)
        for iterable in (list, tuple, set):
            thing = iterable([obj])
            primitive = ser.serialize_entity(self.context, thing)
            self.assertEqual(1, len(primitive))
            for item in primitive:
                self.assertFalse(isinstance(item, base.IronicObject))
            thing2 = ser.deserialize_entity(self.context, primitive)
            self.assertEqual(1, len(thing2))
            for item in thing2:
                self.assertIsInstance(item, MyObj)
