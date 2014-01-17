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
import six

from ironic.common import exception
from ironic.objects import base
from ironic.objects import utils
from ironic.openstack.common import context
from ironic.openstack.common import timeutils
from ironic.tests import base as test_base

gettext.install('ironic')


class MyObj(base.IronicObject):
    version = '1.5'
    fields = {'foo': int,
              'bar': str,
              'missing': str,
              }

    def obj_load_attr(self, attrname):
        setattr(self, attrname, 'loaded!')

    @base.remotable_classmethod
    def get(cls, context):
        obj = cls()
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
        self.assertEqual(utils.datetime_or_none(None), None)
        self.assertRaises(ValueError, utils.datetime_or_none, 'foo')

    def test_datetime_or_str_or_none(self):
        dts = timeutils.isotime()
        dt = timeutils.parse_isotime(dts)
        self.assertEqual(utils.datetime_or_str_or_none(dt), dt)
        self.assertEqual(utils.datetime_or_str_or_none(None), None)
        self.assertEqual(utils.datetime_or_str_or_none(dts), dt)
        self.assertRaises(ValueError, utils.datetime_or_str_or_none, 'foo')

    def test_int_or_none(self):
        self.assertEqual(utils.int_or_none(1), 1)
        self.assertEqual(utils.int_or_none('1'), 1)
        self.assertEqual(utils.int_or_none(None), None)
        self.assertRaises(ValueError, utils.int_or_none, 'foo')

    def test_str_or_none(self):
        class Obj(object):
            pass
        self.assertEqual(utils.str_or_none('foo'), 'foo')
        self.assertEqual(utils.str_or_none(1), '1')
        self.assertEqual(utils.str_or_none(None), None)

    def test_ip_or_none(self):
        ip4 = netaddr.IPAddress('1.2.3.4', 4)
        ip6 = netaddr.IPAddress('1::2', 6)
        self.assertEqual(utils.ip_or_none(4)('1.2.3.4'), ip4)
        self.assertEqual(utils.ip_or_none(6)('1::2'), ip6)
        self.assertEqual(utils.ip_or_none(4)(None), None)
        self.assertEqual(utils.ip_or_none(6)(None), None)
        self.assertRaises(netaddr.AddrFormatError, utils.ip_or_none(4), 'foo')
        self.assertRaises(netaddr.AddrFormatError, utils.ip_or_none(6), 'foo')

    def test_dt_serializer(self):
        class Obj(object):
            foo = utils.dt_serializer('bar')

        obj = Obj()
        obj.bar = timeutils.parse_isotime('1955-11-05T00:00:00Z')
        self.assertEqual(obj.foo(), '1955-11-05T00:00:00Z')
        obj.bar = None
        self.assertEqual(obj.foo(), None)
        obj.bar = 'foo'
        self.assertRaises(AttributeError, obj.foo)

    def test_dt_deserializer(self):
        dt = timeutils.parse_isotime('1955-11-05T00:00:00Z')
        self.assertEqual(utils.dt_deserializer(None, timeutils.isotime(dt)),
                         dt)
        self.assertEqual(utils.dt_deserializer(None, None), None)
        self.assertRaises(ValueError, utils.dt_deserializer, None, 'foo')

    def test_obj_to_primitive_list(self):
        class MyList(base.ObjectListBase, base.IronicObject):
            pass
        mylist = MyList()
        mylist.objects = [1, 2, 3]
        self.assertEqual([1, 2, 3], base.obj_to_primitive(mylist))

    def test_obj_to_primitive_dict(self):
        myobj = MyObj()
        myobj.foo = 1
        myobj.bar = 'foo'
        self.assertEqual({'foo': 1, 'bar': 'foo'},
                         base.obj_to_primitive(myobj))

    def test_obj_to_primitive_recursive(self):
        class MyList(base.ObjectListBase, base.IronicObject):
            pass

        mylist = MyList()
        mylist.objects = [MyObj(), MyObj()]
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
        self.assertEqual(self.remote_object_calls, [])


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
        self.assertEqual(obj.foo, 1)

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
        obj = MyObj()
        obj.foo = 1
        obj.obj_reset_changes()
        self.assertEqual(obj.obj_to_primitive(), expected)

    def test_get_updates(self):
        obj = MyObj()
        self.assertEqual({}, obj.obj_get_changes())
        obj.foo = 123
        self.assertEqual({'foo': 123}, obj.obj_get_changes())
        obj.bar = 'test'
        self.assertEqual({'foo': 123, 'bar': 'test'}, obj.obj_get_changes())
        obj.obj_reset_changes()
        self.assertEqual({}, obj.obj_get_changes())

    def test_object_property(self):
        obj = MyObj()
        obj.foo = 1
        self.assertEqual(obj.foo, 1)

    def test_object_property_type_error(self):
        obj = MyObj()

        def fail():
            obj.foo = 'a'
        self.assertRaises(ValueError, fail)

    def test_object_dict_syntax(self):
        obj = MyObj()
        obj.foo = 123
        obj.bar = 'bar'
        self.assertEqual(obj['foo'], 123)
        self.assertEqual(sorted(obj.items(), key=lambda x: x[0]),
                         [('bar', 'bar'), ('foo', 123)])
        self.assertEqual(sorted(list(obj.iteritems()), key=lambda x: x[0]),
                         [('bar', 'bar'), ('foo', 123)])

    def test_load(self):
        obj = MyObj()
        self.assertEqual(obj.bar, 'loaded!')

    def test_load_in_base(self):
        class Foo(base.IronicObject):
            fields = {'foobar': int}
        obj = Foo()
        # NOTE(danms): Can't use assertRaisesRegexp() because of py26
        raised = False
        try:
            obj.foobar
        except NotImplementedError as ex:
            raised = True
        self.assertTrue(raised)
        self.assertTrue('foobar' in str(ex))

    def test_loaded_in_primitive(self):
        obj = MyObj()
        obj.foo = 1
        obj.obj_reset_changes()
        self.assertEqual(obj.bar, 'loaded!')
        expected = {'ironic_object.name': 'MyObj',
                    'ironic_object.namespace': 'ironic',
                    'ironic_object.version': '1.5',
                    'ironic_object.changes': ['bar'],
                    'ironic_object.data': {'foo': 1,
                                         'bar': 'loaded!'}}
        self.assertEqual(obj.obj_to_primitive(), expected)

    def test_changes_in_primitive(self):
        obj = MyObj()
        obj.foo = 123
        self.assertEqual(obj.obj_what_changed(), set(['foo']))
        primitive = obj.obj_to_primitive()
        self.assertTrue('ironic_object.changes' in primitive)
        obj2 = MyObj.obj_from_primitive(primitive)
        self.assertEqual(obj2.obj_what_changed(), set(['foo']))
        obj2.obj_reset_changes()
        self.assertEqual(obj2.obj_what_changed(), set())

    def test_unknown_objtype(self):
        self.assertRaises(exception.UnsupportedObjectError,
                          base.IronicObject.obj_class_from_name, 'foo', '1.0')

    def test_with_alternate_context(self):
        ctxt1 = context.RequestContext('foo', 'foo')
        ctxt2 = context.RequestContext('bar', tenant='alternate')
        obj = MyObj.get(ctxt1)
        obj.update_test(ctxt2)
        self.assertEqual(obj.bar, 'alternate-context')
        self.assertRemotes()

    def test_orphaned_object(self):
        ctxt = context.get_admin_context()
        obj = MyObj.get(ctxt)
        obj._context = None
        self.assertRaises(exception.OrphanedObjectError,
                          obj.update_test)
        self.assertRemotes()

    def test_changed_1(self):
        ctxt = context.get_admin_context()
        obj = MyObj.get(ctxt)
        obj.foo = 123
        self.assertEqual(obj.obj_what_changed(), set(['foo']))
        obj.update_test(ctxt)
        self.assertEqual(obj.obj_what_changed(), set(['foo', 'bar']))
        self.assertEqual(obj.foo, 123)
        self.assertRemotes()

    def test_changed_2(self):
        ctxt = context.get_admin_context()
        obj = MyObj.get(ctxt)
        obj.foo = 123
        self.assertEqual(obj.obj_what_changed(), set(['foo']))
        obj.save(ctxt)
        self.assertEqual(obj.obj_what_changed(), set([]))
        self.assertEqual(obj.foo, 123)
        self.assertRemotes()

    def test_changed_3(self):
        ctxt = context.get_admin_context()
        obj = MyObj.get(ctxt)
        obj.foo = 123
        self.assertEqual(obj.obj_what_changed(), set(['foo']))
        obj.refresh(ctxt)
        self.assertEqual(obj.obj_what_changed(), set([]))
        self.assertEqual(obj.foo, 321)
        self.assertEqual(obj.bar, 'refreshed')
        self.assertRemotes()

    def test_changed_4(self):
        ctxt = context.get_admin_context()
        obj = MyObj.get(ctxt)
        obj.bar = 'something'
        self.assertEqual(obj.obj_what_changed(), set(['bar']))
        obj.modify_save_modify(ctxt)
        self.assertEqual(obj.obj_what_changed(), set(['foo']))
        self.assertEqual(obj.foo, 42)
        self.assertEqual(obj.bar, 'meow')
        self.assertRemotes()

    def test_static_result(self):
        ctxt = context.get_admin_context()
        obj = MyObj.get(ctxt)
        self.assertEqual(obj.bar, 'bar')
        result = obj.marco()
        self.assertEqual(result, 'polo')
        self.assertRemotes()

    def test_updates(self):
        ctxt = context.get_admin_context()
        obj = MyObj.get(ctxt)
        self.assertEqual(obj.foo, 1)
        obj.update_test()
        self.assertEqual(obj.bar, 'updated')
        self.assertRemotes()

    def test_base_attributes(self):
        dt = datetime.datetime(1955, 11, 5)
        obj = MyObj()
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
        self.assertEqual(obj.obj_to_primitive(), expected)

    def test_contains(self):
        obj = MyObj()
        self.assertFalse('foo' in obj)
        obj.foo = 1
        self.assertTrue('foo' in obj)
        self.assertFalse('does_not_exist' in obj)


class TestObject(_LocalTest, _TestObject):
    pass


class TestObjectListBase(test_base.TestCase):
    def test_list_like_operations(self):
        class Foo(base.ObjectListBase, base.IronicObject):
            pass

        objlist = Foo()
        objlist._context = 'foo'
        objlist.objects = [1, 2, 3]
        self.assertEqual(list(objlist), objlist.objects)
        self.assertEqual(len(objlist), 3)
        self.assertIn(2, objlist)
        self.assertEqual(list(objlist[:1]), [1])
        self.assertEqual(objlist[:1]._context, 'foo')
        self.assertEqual(objlist[2], 3)
        self.assertEqual(objlist.count(1), 1)
        self.assertEqual(objlist.index(2), 1)

    def test_serialization(self):
        class Foo(base.ObjectListBase, base.IronicObject):
            pass

        class Bar(base.IronicObject):
            fields = {'foo': str}

        obj = Foo()
        obj.objects = []
        for i in 'abc':
            bar = Bar()
            bar.foo = i
            obj.objects.append(bar)

        obj2 = base.IronicObject.obj_from_primitive(obj.obj_to_primitive())
        self.assertFalse(obj is obj2)
        self.assertEqual([x.foo for x in obj],
                         [y.foo for y in obj2])


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
        ctxt = context.get_admin_context()
        obj = MyObj()
        primitive = ser.serialize_entity(ctxt, obj)
        self.assertTrue('ironic_object.name' in primitive)
        obj2 = ser.deserialize_entity(ctxt, primitive)
        self.assertIsInstance(obj2, MyObj)
        self.assertEqual(ctxt, obj2._context)

    def test_object_serialization_iterables(self):
        ser = base.IronicObjectSerializer()
        ctxt = context.get_admin_context()
        obj = MyObj()
        for iterable in (list, tuple, set):
            thing = iterable([obj])
            primitive = ser.serialize_entity(ctxt, thing)
            self.assertEqual(1, len(primitive))
            for item in primitive:
                self.assertFalse(isinstance(item, base.IronicObject))
            thing2 = ser.deserialize_entity(ctxt, primitive)
            self.assertEqual(1, len(thing2))
            for item in thing2:
                self.assertIsInstance(item, MyObj)
