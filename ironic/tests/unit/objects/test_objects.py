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
import types
from unittest import mock

import iso8601
from oslo_utils import timeutils
from oslo_versionedobjects import base as object_base
from oslo_versionedobjects import exception as object_exception
from oslo_versionedobjects import fixture as object_fixture

from ironic.common import context
from ironic.common import release_mappings
from ironic.conf import CONF
from ironic.objects import base
from ironic.objects import fields
from ironic.tests import base as test_base


@base.IronicObjectRegistry.register
class MyObj(base.IronicObject, object_base.VersionedObjectDictCompat):
    VERSION = '1.5'

    fields = {'foo': fields.IntegerField(),
              'bar': fields.StringField(),
              'missing': fields.StringField(),
              # nested object added as string for simplicity
              'nested_object': fields.StringField(),
              }

    def _set_from_db_object(self, context, db_object, fields=None):
        fields = set(fields or self.fields) - {'nested_object'}
        super(MyObj, self)._set_from_db_object(context, db_object, fields)
        # some special manipulation with nested_object here
        self['nested_object'] = db_object.get('nested_object', '') + 'test'

    def obj_load_attr(self, attrname):
        if attrname == 'version':
            setattr(self, attrname, None)
        else:
            setattr(self, attrname, 'loaded!')

    @object_base.remotable_classmethod
    def query(cls, context):
        obj = cls(context)
        obj.foo = 1
        obj.bar = 'bar'
        obj.obj_reset_changes()
        return obj

    @object_base.remotable
    def marco(self, context=None):
        return 'polo'

    @object_base.remotable
    def update_test(self, context=None):
        if context and context.project_id == 'alternate':
            self.bar = 'alternate-context'
        else:
            self.bar = 'updated'

    @object_base.remotable
    def save(self, context=None):
        self.do_version_changes_for_db()
        self.obj_reset_changes()

    @object_base.remotable
    def refresh(self, context=None):
        self.foo = 321
        self.bar = 'refreshed'
        self.obj_reset_changes()

    @object_base.remotable
    def modify_save_modify(self, context=None):
        self.bar = 'meow'
        self.save()
        self.foo = 42

    def _convert_to_version(self, target_version,
                            remove_unavailable_fields=True):
        if target_version == '1.5':
            self.missing = 'foo'
        elif self.missing:
            if remove_unavailable_fields:
                delattr(self, 'missing')
            else:
                self.missing = ''


class MyObj2(object):
    @classmethod
    def obj_name(cls):
        return 'MyObj'

    @object_base.remotable_classmethod
    def get(cls, *args, **kwargs):
        pass


@base.IronicObjectRegistry.register_if(False)
class TestSubclassedObject(MyObj):
    fields = {'new_field': fields.StringField()}


class _LocalTest(test_base.TestCase):
    def setUp(self):
        super(_LocalTest, self).setUp()
        # Just in case
        base.IronicObject.indirection_api = None


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
        self.assertRaises(object_exception.UnsupportedObjectError,
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

    def test_load(self):
        obj = MyObj(self.context)
        self.assertEqual('loaded!', obj.bar)

    def test_load_in_base(self):
        @base.IronicObjectRegistry.register_if(False)
        class Foo(base.IronicObject, object_base.VersionedObjectDictCompat):
            fields = {'foobar': fields.IntegerField()}
        obj = Foo(self.context)

        self.assertRaisesRegex(
            NotImplementedError, "Cannot load 'foobar' in the base class",
            getattr, obj, 'foobar')

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
        self.assertIn('ironic_object.changes', primitive)
        obj2 = MyObj.obj_from_primitive(primitive)
        self.assertEqual(set(['foo']), obj2.obj_what_changed())
        obj2.obj_reset_changes()
        self.assertEqual(set(), obj2.obj_what_changed())

    def test_unknown_objtype(self):
        self.assertRaises(object_exception.UnsupportedObjectError,
                          base.IronicObject.obj_class_from_name, 'foo', '1.0')

    def test_with_alternate_context(self):
        ctxt1 = context.RequestContext(auth_token='foo', project_id='foo')
        ctxt2 = context.RequestContext(auth_token='bar',
                                       project_id='alternate')
        obj = MyObj.query(ctxt1)
        obj.update_test(ctxt2)
        self.assertEqual('alternate-context', obj.bar)

    def test_orphaned_object(self):
        obj = MyObj.query(self.context)
        obj._context = None
        self.assertRaises(object_exception.OrphanedObjectError,
                          obj.update_test)

    def test_changed_1(self):
        obj = MyObj.query(self.context)
        obj.foo = 123
        self.assertEqual(set(['foo']), obj.obj_what_changed())
        obj.update_test(self.context)
        self.assertEqual(set(['foo', 'bar']), obj.obj_what_changed())
        self.assertEqual(123, obj.foo)

    def test_changed_2(self):
        obj = MyObj.query(self.context)
        obj.foo = 123
        self.assertEqual(set(['foo']), obj.obj_what_changed())
        obj.save()
        self.assertEqual(set([]), obj.obj_what_changed())
        self.assertEqual(123, obj.foo)

    def test_changed_3(self):
        obj = MyObj.query(self.context)
        obj.foo = 123
        self.assertEqual(set(['foo']), obj.obj_what_changed())
        obj.refresh()
        self.assertEqual(set([]), obj.obj_what_changed())
        self.assertEqual(321, obj.foo)
        self.assertEqual('refreshed', obj.bar)

    def test_changed_4(self):
        obj = MyObj.query(self.context)
        obj.bar = 'something'
        self.assertEqual(set(['bar']), obj.obj_what_changed())
        obj.modify_save_modify(self.context)
        self.assertEqual(set(['foo']), obj.obj_what_changed())
        self.assertEqual(42, obj.foo)
        self.assertEqual('meow', obj.bar)

    def test_static_result(self):
        obj = MyObj.query(self.context)
        self.assertEqual('bar', obj.bar)
        result = obj.marco()
        self.assertEqual('polo', result)

    def test_updates(self):
        obj = MyObj.query(self.context)
        self.assertEqual(1, obj.foo)
        obj.update_test()
        self.assertEqual('updated', obj.bar)

    def test_base_attributes(self):
        dt = datetime.datetime(1955, 11, 5, 0, 0, tzinfo=iso8601.UTC)
        datatime = fields.DateTimeField()
        obj = MyObj(self.context)
        obj.created_at = dt
        obj.updated_at = dt
        expected = {'ironic_object.name': 'MyObj',
                    'ironic_object.namespace': 'ironic',
                    'ironic_object.version': '1.5',
                    'ironic_object.changes':
                        ['created_at', 'updated_at'],
                    'ironic_object.data':
                        {'created_at': datatime.stringify(dt),
                         'updated_at': datatime.stringify(dt),
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
        self.assertNotIn('foo', obj)
        obj.foo = 1
        self.assertIn('foo', obj)
        self.assertNotIn('does_not_exist', obj)

    def test_obj_attr_is_set(self):
        obj = MyObj(self.context, foo=1)
        self.assertTrue(obj.obj_attr_is_set('foo'))
        self.assertFalse(obj.obj_attr_is_set('bar'))
        self.assertRaises(AttributeError, obj.obj_attr_is_set, 'bang')

    def test_get(self):
        obj = MyObj(self.context, foo=1)
        # Foo has value, should not get the default
        self.assertEqual(1, obj.get('foo', 2))
        # Foo has value, should return the value without error
        self.assertEqual(1, obj.get('foo'))
        # Bar is not loaded, so we should get the default
        self.assertEqual('not-loaded', obj.get('bar', 'not-loaded'))
        # Bar without a default should lazy-load
        self.assertEqual('loaded!', obj.get('bar'))
        # Bar now has a default, but loaded value should be returned
        self.assertEqual('loaded!', obj.get('bar', 'not-loaded'))
        # Invalid attribute should raise AttributeError
        self.assertRaises(AttributeError, obj.get, 'nothing')
        # ...even with a default
        self.assertRaises(AttributeError, obj.get, 'nothing', 3)

    def test_object_inheritance(self):
        base_fields = list(base.IronicObject.fields)
        myobj_fields = ['foo', 'bar', 'missing', 'nested_object'] + base_fields
        myobj3_fields = ['new_field']
        self.assertTrue(issubclass(TestSubclassedObject, MyObj))
        self.assertEqual(len(myobj_fields), len(MyObj.fields))
        self.assertEqual(set(myobj_fields), set(MyObj.fields))
        self.assertEqual(len(myobj_fields) + len(myobj3_fields),
                         len(TestSubclassedObject.fields))
        self.assertEqual(set(myobj_fields) | set(myobj3_fields),
                         set(TestSubclassedObject.fields))

    def _test_get_changes(self, target_version='1.5'):
        obj = MyObj(self.context)
        self.assertEqual('1.5', obj.VERSION)
        self.assertEqual(target_version, obj.get_target_version())
        self.assertEqual({}, obj.obj_get_changes())
        obj.foo = 123
        self.assertEqual({'foo': 123}, obj.obj_get_changes())
        obj.bar = 'test'
        obj.missing = 'test'  # field which is missing in v1.4
        self.assertEqual({'foo': 123, 'bar': 'test', 'missing': 'test'},
                         obj.obj_get_changes())
        obj.obj_reset_changes()
        self.assertEqual({}, obj.obj_get_changes())

    def test_get_changes(self):
        self._test_get_changes()

    @mock.patch('ironic.common.release_mappings.RELEASE_MAPPING',
                autospec=True)
    def test_get_changes_pinned(self, mock_release_mapping):
        # obj_get_changes() is not affected by pinning
        CONF.set_override('pin_release_version',
                          release_mappings.RELEASE_VERSIONS[-1])
        mock_release_mapping.__getitem__.return_value = {
            'objects': {
                'MyObj': ['1.4'],
            }
        }
        self._test_get_changes(target_version='1.4')

    @mock.patch('ironic.common.release_mappings.RELEASE_MAPPING',
                autospec=True)
    def test_get_changes_pinned_2versions(self, mock_release_mapping):
        # obj_get_changes() is not affected by pinning
        CONF.set_override('pin_release_version',
                          release_mappings.RELEASE_VERSIONS[-1])
        mock_release_mapping.__getitem__.return_value = {
            'objects': {
                'MyObj': ['1.3', '1.4'],
            }
        }
        self._test_get_changes(target_version='1.4')

    def test_convert_to_version_same(self):
        # no changes
        obj = MyObj(self.context)
        self.assertEqual('1.5', obj.VERSION)
        obj.convert_to_version('1.5', remove_unavailable_fields=False)
        self.assertEqual('1.5', obj.VERSION)
        self.assertEqual(obj.__class__.VERSION, obj.VERSION)
        self.assertEqual({}, obj.obj_get_changes())

    def test_convert_to_version_new(self):
        obj = MyObj(self.context)
        obj.VERSION = '1.4'
        obj.convert_to_version('1.5', remove_unavailable_fields=False)
        self.assertEqual('1.5', obj.VERSION)
        self.assertEqual(obj.__class__.VERSION, obj.VERSION)
        self.assertEqual({'missing': 'foo'}, obj.obj_get_changes())

    def test_convert_to_version_old(self):
        obj = MyObj(self.context)
        obj.missing = 'something'
        obj.obj_reset_changes()
        obj.convert_to_version('1.4', remove_unavailable_fields=True)
        self.assertEqual('1.4', obj.VERSION)
        self.assertEqual({}, obj.obj_get_changes())

    def test_convert_to_version_old_keep(self):
        obj = MyObj(self.context)
        obj.missing = 'something'
        obj.obj_reset_changes()
        obj.convert_to_version('1.4', remove_unavailable_fields=False)
        self.assertEqual('1.4', obj.VERSION)
        self.assertEqual({'missing': ''}, obj.obj_get_changes())

    @mock.patch.object(MyObj, 'convert_to_version', autospec=True)
    def test_do_version_changes_for_db(self, mock_convert):
        # no object conversion
        obj = MyObj(self.context)
        self.assertEqual('1.5', obj.VERSION)
        self.assertEqual('1.5', obj.get_target_version())
        self.assertEqual({}, obj.obj_get_changes())
        obj.foo = 123
        obj.bar = 'test'
        obj.missing = 'test'  # field which is missing in v1.4
        self.assertEqual({'foo': 123, 'bar': 'test', 'missing': 'test'},
                         obj.obj_get_changes())
        changes = obj.do_version_changes_for_db()
        self.assertEqual({'foo': 123, 'bar': 'test', 'missing': 'test',
                          'version': '1.5'}, changes)
        self.assertEqual('1.5', obj.VERSION)
        self.assertFalse(mock_convert.called)

    @mock.patch.object(MyObj, 'convert_to_version', autospec=True)
    @mock.patch.object(base.IronicObject, 'get_target_version',
                       spec_set=types.FunctionType)
    def test_do_version_changes_for_db_pinned(self, mock_target_version,
                                              mock_convert):
        # obj is same version as pinned, no conversion done
        mock_target_version.return_value = '1.4'

        obj = MyObj(self.context)
        obj.VERSION = '1.4'
        self.assertEqual('1.4', obj.get_target_version())
        obj.foo = 123
        obj.bar = 'test'
        self.assertEqual({'foo': 123, 'bar': 'test'}, obj.obj_get_changes())
        self.assertEqual('1.4', obj.VERSION)
        changes = obj.do_version_changes_for_db()
        self.assertEqual({'foo': 123, 'bar': 'test', 'version': '1.4'},
                         changes)
        self.assertEqual('1.4', obj.VERSION)
        mock_target_version.assert_called_with()
        self.assertFalse(mock_convert.called)

    @mock.patch.object(base.IronicObject, 'get_target_version',
                       spec_set=types.FunctionType)
    def test_do_version_changes_for_db_downgrade(self, mock_target_version):
        # obj is 1.5; convert to 1.4
        mock_target_version.return_value = '1.4'

        obj = MyObj(self.context)
        obj.foo = 123
        obj.bar = 'test'
        obj.missing = 'something'
        self.assertEqual({'foo': 123, 'bar': 'test', 'missing': 'something'},
                         obj.obj_get_changes())
        self.assertEqual('1.5', obj.VERSION)
        changes = obj.do_version_changes_for_db()
        self.assertEqual({'foo': 123, 'bar': 'test', 'missing': '',
                          'version': '1.4'}, changes)
        self.assertEqual('1.4', obj.VERSION)
        mock_target_version.assert_called_with()

    @mock.patch('ironic.common.release_mappings.RELEASE_MAPPING',
                autospec=True)
    def _test__from_db_object(self, version, mock_release_mapping):
        mock_release_mapping.__getitem__.return_value = {
            'objects': {
                'MyObj': ['1.4'],
            }
        }
        missing = ''
        if version == '1.5':
            missing = 'foo'
        obj = MyObj(self.context)
        dbobj = {'created_at': timeutils.utcnow(),
                 'updated_at': timeutils.utcnow(),
                 'version': version,
                 'foo': 123, 'bar': 'test', 'missing': missing}
        MyObj._from_db_object(self.context, obj, dbobj)
        self.assertEqual(obj.__class__.VERSION, obj.VERSION)
        self.assertEqual(123, obj.foo)
        self.assertEqual('test', obj.bar)
        self.assertEqual('foo', obj.missing)
        self.assertFalse(mock_release_mapping.called)

    def test__from_db_object(self):
        self._test__from_db_object('1.5')

    def test__from_db_object_old(self):
        self._test__from_db_object('1.4')

    def test__from_db_object_map_version_bad(self):
        obj = MyObj(self.context)
        dbobj = {'created_at': timeutils.utcnow(),
                 'updated_at': timeutils.utcnow(),
                 'version': '1.99',
                 'foo': 123, 'bar': 'test', 'missing': ''}
        self.assertRaises(object_exception.IncompatibleObjectVersion,
                          MyObj._from_db_object, self.context, obj, dbobj)

    def test_get_target_version_no_pin(self):
        obj = MyObj(self.context)
        self.assertEqual('1.5', obj.get_target_version())

    @mock.patch('ironic.common.release_mappings.RELEASE_MAPPING',
                autospec=True)
    def test_get_target_version_pinned(self, mock_release_mapping):
        CONF.set_override('pin_release_version',
                          release_mappings.RELEASE_VERSIONS[-1])
        mock_release_mapping.__getitem__.return_value = {
            'objects': {
                'MyObj': ['1.4'],
            }
        }
        obj = MyObj(self.context)
        self.assertEqual('1.4', obj.get_target_version())

    @mock.patch('ironic.common.release_mappings.RELEASE_MAPPING',
                autospec=True)
    def test_get_target_version_pinned_no_myobj(self, mock_release_mapping):
        CONF.set_override('pin_release_version',
                          release_mappings.RELEASE_VERSIONS[-1])
        mock_release_mapping.__getitem__.return_value = {
            'objects': {
                'NotMyObj': ['1.4'],
            }
        }
        obj = MyObj(self.context)
        self.assertEqual('1.5', obj.get_target_version())

    @mock.patch('ironic.common.release_mappings.RELEASE_MAPPING',
                autospec=True)
    def test_get_target_version_pinned_bad(self, mock_release_mapping):
        CONF.set_override('pin_release_version',
                          release_mappings.RELEASE_VERSIONS[-1])
        mock_release_mapping.__getitem__.return_value = {
            'objects': {
                'MyObj': ['1.6'],
            }
        }
        obj = MyObj(self.context)
        self.assertRaises(object_exception.IncompatibleObjectVersion,
                          obj.get_target_version)

    @mock.patch.object(base.IronicObject, 'get_target_version',
                       spec_set=types.FunctionType)
    def test_supports_version(self, mock_target_version):
        mock_target_version.return_value = "1.5"
        obj = MyObj(self.context)
        self.assertTrue(obj.supports_version((1, 5)))
        self.assertFalse(obj.supports_version((1, 6)))

    def test_obj_fields(self):
        @base.IronicObjectRegistry.register_if(False)
        class TestObj(base.IronicObject,
                      object_base.VersionedObjectDictCompat):
            fields = {'foo': fields.IntegerField()}
            obj_extra_fields = ['bar']

            @property
            def bar(self):
                return 'this is bar'

        obj = TestObj(self.context)
        self.assertEqual(set(['created_at', 'updated_at', 'foo', 'bar']),
                         set(obj.obj_fields))

    def test_refresh_object(self):
        @base.IronicObjectRegistry.register_if(False)
        class TestObj(base.IronicObject,
                      object_base.VersionedObjectDictCompat):
            fields = {'foo': fields.IntegerField(),
                      'bar': fields.StringField()}

        obj = TestObj(self.context)
        current_obj = TestObj(self.context)
        obj.foo = 10
        obj.bar = 'obj.bar'
        current_obj.foo = 2
        current_obj.bar = 'current.bar'
        obj.obj_refresh(current_obj)
        self.assertEqual(2, obj.foo)
        self.assertEqual('current.bar', obj.bar)

    def test_obj_constructor(self):
        obj = MyObj(self.context, foo=123, bar='abc')
        self.assertEqual(123, obj.foo)
        self.assertEqual('abc', obj.bar)
        self.assertEqual(set(['foo', 'bar']), obj.obj_what_changed())

    def test_assign_value_without_DictCompat(self):
        class TestObj(base.IronicObject):
            fields = {'foo': fields.IntegerField(),
                      'bar': fields.StringField()}
        obj = TestObj(self.context)
        obj.foo = 10
        err_message = ''
        try:
            obj['bar'] = 'value'
        except TypeError as e:
            err_message = str(e)
        finally:
            self.assertIn("'TestObj' object does not support item assignment",
                          err_message)

    def test_as_dict(self):
        obj = MyObj(self.context)
        obj.foo = 1
        result = obj.as_dict()
        expected = {'foo': 1}
        self.assertEqual(expected, result)

    def test_as_dict_with_nested_object(self):
        @base.IronicObjectRegistry.register_if(False)
        class TestObj(base.IronicObject,
                      object_base.VersionedObjectDictCompat):
            fields = {'my_obj': fields.ObjectField('MyObj')}

        obj1 = MyObj(self.context)
        obj1.foo = 1
        obj2 = TestObj(self.context)
        obj2.my_obj = obj1
        result = obj2.as_dict()
        expected = {'my_obj': {'foo': 1}}
        self.assertEqual(expected, result)

    def test_as_dict_with_nested_object_list(self):
        @base.IronicObjectRegistry.register_if(False)
        class TestObj(base.IronicObjectListBase, base.IronicObject):
            fields = {'objects': fields.ListOfObjectsField('MyObj')}

        obj1 = MyObj(self.context)
        obj1.foo = 1
        obj2 = TestObj(self.context)
        obj2.objects = [obj1]
        result = obj2.as_dict()
        expected = {'objects': [{'foo': 1}]}
        self.assertEqual(expected, result)


class TestObject(_LocalTest, _TestObject):
    pass


# The hashes are to help developers to check if a change in an object needs a
# version bump. It is an MD5 hash of the object fields and remotable methods.
# The fingerprint values should only be changed if there is a version bump.
expected_object_fingerprints = {
    'Node': '1.35-aee8ecf5c4d0ed590eb484762aee7fca',
    'MyObj': '1.5-9459d30d6954bffc7a9afd347a807ca6',
    'Chassis': '1.3-d656e039fd8ae9f34efc232ab3980905',
    'Port': '1.10-67381b065c597c8d3a13c5dbc6243c33',
    'Portgroup': '1.4-71923a81a86743b313b190f5c675e258',
    'Conductor': '1.3-d3f53e853b4d58cae5bfbd9a8341af4a',
    'EventType': '1.1-aa2ba1afd38553e3880c267404e8d370',
    'NotificationPublisher': '1.0-51a09397d6c0687771fb5be9a999605d',
    'NodePayload': '1.15-86ee30dbf374be4cf17c5b501d9e2e7b',
    'NodeSetPowerStateNotification': '1.0-59acc533c11d306f149846f922739c15',
    'NodeSetPowerStatePayload': '1.15-3c64b07a2b96c2661e7743b47ed43705',
    'NodeCorrectedPowerStateNotification':
        '1.0-59acc533c11d306f149846f922739c15',
    'NodeCorrectedPowerStatePayload': '1.15-59a224a9191cdc9f1acc2e0dcd2d3adb',
    'NodeSetProvisionStateNotification':
        '1.0-59acc533c11d306f149846f922739c15',
    'NodeSetProvisionStatePayload': '1.16-c5a8eea43c514baf721fc61ce5d9d5a4',
    'VolumeConnector': '1.0-3e0252c0ab6e6b9d158d09238a577d97',
    'VolumeTarget': '1.0-0b10d663d8dae675900b2c7548f76f5e',
    'ChassisCRUDNotification': '1.0-59acc533c11d306f149846f922739c15',
    'ChassisCRUDPayload': '1.0-dce63895d8186279a7dd577cffccb202',
    'NodeCRUDNotification': '1.0-59acc533c11d306f149846f922739c15',
    'NodeCRUDPayload': '1.13-8f673253ff8d7389897a6a80d224ac33',
    'PortCRUDNotification': '1.0-59acc533c11d306f149846f922739c15',
    'PortCRUDPayload': '1.4-9411a1701077ae9dc0aea27d6bf586fc',
    'NodeMaintenanceNotification': '1.0-59acc533c11d306f149846f922739c15',
    'NodeConsoleNotification': '1.0-59acc533c11d306f149846f922739c15',
    'PortgroupCRUDNotification': '1.0-59acc533c11d306f149846f922739c15',
    'PortgroupCRUDPayload': '1.0-b73c1fecf0cef3aa56bbe3c7e2275018',
    'VolumeConnectorCRUDNotification': '1.0-59acc533c11d306f149846f922739c15',
    'VolumeConnectorCRUDPayload': '1.0-5e8dbb41e05b6149d8f7bfd4daff9339',
    'VolumeTargetCRUDNotification': '1.0-59acc533c11d306f149846f922739c15',
    'VolumeTargetCRUDPayload': '1.0-30dcc4735512c104a3a36a2ae1e2aeb2',
    'Trait': '1.0-3f26cb70c8a10a3807d64c219453e347',
    'TraitList': '1.0-33a2e1bb91ad4082f9f63429b77c1244',
    'BIOSSetting': '1.1-1137db88675a4e2d7f7bcc3a0d52345a',
    'BIOSSettingList': '1.0-33a2e1bb91ad4082f9f63429b77c1244',
    'Allocation': '1.1-38937f2854722f1057ec667b12878708',
    'AllocationCRUDNotification': '1.0-59acc533c11d306f149846f922739c15',
    'AllocationCRUDPayload': '1.1-3c8849932b80380bb96587ff62e8f087',
    'DeployTemplate': '1.1-4e30c8e9098595e359bb907f095bf1a9',
    'DeployTemplateCRUDNotification': '1.0-59acc533c11d306f149846f922739c15',
    'DeployTemplateCRUDPayload': '1.0-200857e7e715f58a5b6d6b700ab73a3b',
    'Deployment': '1.0-ff10ae028c5968f1596131d85d7f5f9d',
}


class TestObjectVersions(test_base.TestCase):

    def test_object_version_check(self):
        classes = base.IronicObjectRegistry.obj_classes()
        checker = object_fixture.ObjectVersionChecker(obj_classes=classes)
        # Compute the difference between actual fingerprints and
        # expect fingerprints. expect = actual = {} if there is no change.
        expect, actual = checker.test_hashes(expected_object_fingerprints)
        self.assertEqual(expect, actual,
                         "Some objects fields or remotable methods have been "
                         "modified. Please make sure the version of those "
                         "objects have been bumped and then update "
                         "expected_object_fingerprints with the new hashes. ")


class TestObjectSerializer(test_base.TestCase):

    def test_object_serialization(self):
        ser = base.IronicObjectSerializer()
        obj = MyObj(self.context)
        primitive = ser.serialize_entity(self.context, obj)
        self.assertIn('ironic_object.name', primitive)
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
                self.assertNotIsInstance(item, base.IronicObject)
            thing2 = ser.deserialize_entity(self.context, primitive)
            self.assertEqual(1, len(thing2))
            for item in thing2:
                self.assertIsInstance(item, MyObj)

    @mock.patch('ironic.objects.base.IronicObject.indirection_api',
                autospec=True)
    def _test_deserialize_entity_newer(self, obj_version, backported_to,
                                       mock_indirection_api,
                                       my_version='1.6'):
        ser = base.IronicObjectSerializer()
        backported_obj = MyObj()
        mock_indirection_api.object_backport_versions.return_value \
            = backported_obj

        @base.IronicObjectRegistry.register
        class MyTestObj(MyObj):
            VERSION = my_version

        obj = MyTestObj(self.context)
        obj.VERSION = obj_version
        primitive = obj.obj_to_primitive()
        result = ser.deserialize_entity(self.context, primitive)
        if backported_to is None:
            self.assertFalse(
                mock_indirection_api.object_backport_versions.called)
        else:
            self.assertEqual(backported_obj, result)
            versions = object_base.obj_tree_get_versions('MyTestObj')
            mock_indirection_api.object_backport_versions.assert_called_with(
                self.context, primitive, versions)

    def test_deserialize_entity_newer_version_backports(self):
        "Test object with unsupported (newer) version"
        self._test_deserialize_entity_newer('1.25', '1.6')

    def test_deserialize_entity_same_revision_does_not_backport(self):
        "Test object with supported revision"
        self._test_deserialize_entity_newer('1.6', None)

    def test_deserialize_entity_newer_revision_does_not_backport_zero(self):
        "Test object with supported revision"
        self._test_deserialize_entity_newer('1.6.0', None)

    def test_deserialize_entity_newer_revision_does_not_backport(self):
        "Test object with supported (newer) revision"
        self._test_deserialize_entity_newer('1.6.1', None)

    def test_deserialize_entity_newer_version_passes_revision(self):
        "Test object with unsupported (newer) version and revision"
        self._test_deserialize_entity_newer('1.7', '1.6.1', my_version='1.6.1')

    @mock.patch('ironic.common.release_mappings.RELEASE_MAPPING',
                autospec=True)
    def test_deserialize_entity_pin_ignored(self, mock_release_mapping):
        # Deserializing doesn't look at pinning
        CONF.set_override('pin_release_version',
                          release_mappings.RELEASE_VERSIONS[-1])
        mock_release_mapping.__getitem__.return_value = {
            'objects': {
                'MyTestObj': ['1.0'],
            }
        }
        ser = base.IronicObjectSerializer()

        @base.IronicObjectRegistry.register
        class MyTestObj(MyObj):
            VERSION = '1.1'

        obj = MyTestObj(self.context)
        primitive = obj.obj_to_primitive()
        result = ser.deserialize_entity(self.context, primitive)
        self.assertEqual('1.1', result.VERSION)
        self.assertEqual('1.0', result.get_target_version())
        self.assertFalse(mock_release_mapping.called)

    @mock.patch.object(base.IronicObject, 'convert_to_version', autospec=True)
    @mock.patch.object(base.IronicObject, 'get_target_version', autospec=True)
    def test_serialize_entity_unpinned_api(self, mock_version, mock_convert):
        """Test single element serializer with no backport, unpinned."""
        mock_version.return_value = MyObj.VERSION
        serializer = base.IronicObjectSerializer(is_server=False)
        obj = MyObj(self.context)
        obj.foo = 1
        obj.bar = 'text'
        obj.missing = 'textt'
        primitive = serializer.serialize_entity(self.context, obj)
        self.assertEqual('1.5', primitive['ironic_object.version'])
        data = primitive['ironic_object.data']
        self.assertEqual(1, data['foo'])
        self.assertEqual('text', data['bar'])
        self.assertEqual('textt', data['missing'])
        changes = primitive['ironic_object.changes']
        self.assertEqual(set(['foo', 'bar', 'missing']), set(changes))
        self.assertFalse(mock_version.called)
        self.assertFalse(mock_convert.called)

    @mock.patch.object(base.IronicObject, 'convert_to_version', autospec=True)
    @mock.patch.object(base.IronicObject, 'get_target_version',
                       spec_set=types.FunctionType)
    def test_serialize_entity_unpinned_conductor(self, mock_version,
                                                 mock_convert):
        """Test single element serializer with no backport, unpinned."""
        mock_version.return_value = MyObj.VERSION
        serializer = base.IronicObjectSerializer(is_server=True)
        obj = MyObj(self.context)
        obj.foo = 1
        obj.bar = 'text'
        obj.missing = 'textt'
        primitive = serializer.serialize_entity(self.context, obj)
        self.assertEqual('1.5', primitive['ironic_object.version'])
        data = primitive['ironic_object.data']
        self.assertEqual(1, data['foo'])
        self.assertEqual('text', data['bar'])
        self.assertEqual('textt', data['missing'])
        changes = primitive['ironic_object.changes']
        self.assertEqual(set(['foo', 'bar', 'missing']), set(changes))
        mock_version.assert_called_once_with()
        self.assertFalse(mock_convert.called)

    @mock.patch.object(base.IronicObject, 'get_target_version', autospec=True)
    def test_serialize_entity_pinned_api(self, mock_version):
        """Test single element serializer with backport to pinned version."""
        mock_version.return_value = '1.4'

        serializer = base.IronicObjectSerializer(is_server=False)
        obj = MyObj(self.context)
        obj.foo = 1
        obj.bar = 'text'
        obj.missing = 'miss'
        self.assertEqual('1.5', obj.VERSION)
        primitive = serializer.serialize_entity(self.context, obj)
        self.assertEqual('1.5', primitive['ironic_object.version'])
        data = primitive['ironic_object.data']
        self.assertEqual(1, data['foo'])
        self.assertEqual('text', data['bar'])
        self.assertEqual('miss', data['missing'])
        self.assertFalse(mock_version.called)

    @mock.patch.object(base.IronicObject, 'get_target_version',
                       spec_set=types.FunctionType)
    def test_serialize_entity_pinned_conductor(self, mock_version):
        """Test single element serializer with backport to pinned version."""
        mock_version.return_value = '1.4'

        serializer = base.IronicObjectSerializer(is_server=True)
        obj = MyObj(self.context)
        obj.foo = 1
        obj.bar = 'text'
        obj.missing = 'miss'
        self.assertEqual('1.5', obj.VERSION)
        primitive = serializer.serialize_entity(self.context, obj)
        self.assertEqual('1.4', primitive['ironic_object.version'])
        data = primitive['ironic_object.data']
        self.assertEqual(1, data['foo'])
        self.assertEqual('text', data['bar'])
        self.assertNotIn('missing', data)
        self.assertNotIn('ironic_object.changes', primitive)
        mock_version.assert_called_once_with()

    @mock.patch.object(base.IronicObject, 'get_target_version',
                       spec_set=types.FunctionType)
    def test_serialize_entity_invalid_pin(self, mock_version):
        mock_version.side_effect = object_exception.InvalidTargetVersion(
            version='1.6')

        serializer = base.IronicObjectSerializer(is_server=True)
        obj = MyObj(self.context)
        self.assertRaises(object_exception.InvalidTargetVersion,
                          serializer.serialize_entity, self.context, obj)
        mock_version.assert_called_once_with()

    @mock.patch.object(base.IronicObject, 'convert_to_version', autospec=True)
    def _test__process_object(self, mock_convert, is_server=True):
        obj = MyObj(self.context)
        obj.foo = 1
        obj.bar = 'text'
        obj.missing = 'miss'
        primitive = obj.obj_to_primitive()

        serializer = base.IronicObjectSerializer(is_server=is_server)
        obj2 = serializer._process_object(self.context, primitive)
        self.assertEqual(obj.foo, obj2.foo)
        self.assertEqual(obj.bar, obj2.bar)
        self.assertEqual(obj.missing, obj2.missing)
        self.assertEqual(obj.VERSION, obj2.VERSION)
        self.assertFalse(mock_convert.called)

    def test__process_object_api(self):
        self._test__process_object(is_server=False)

    def test__process_object_conductor(self):
        self._test__process_object(is_server=True)

    @mock.patch.object(base.IronicObject, 'convert_to_version', autospec=True)
    def _test__process_object_convert(self, is_server, mock_convert):
        obj = MyObj(self.context)
        obj.foo = 1
        obj.bar = 'text'
        obj.missing = ''
        obj.VERSION = '1.4'
        primitive = obj.obj_to_primitive()

        serializer = base.IronicObjectSerializer(is_server=is_server)
        serializer._process_object(self.context, primitive)
        mock_convert.assert_called_once_with(
            mock.ANY, '1.5', remove_unavailable_fields=not is_server)

    def test__process_object_convert_api(self):
        self._test__process_object_convert(False)

    def test__process_object_convert_conductor(self):
        self._test__process_object_convert(True)


class TestRegistry(test_base.TestCase):
    @mock.patch('ironic.objects.base.objects', autospec=True)
    def test_hook_chooses_newer_properly(self, mock_objects):
        reg = base.IronicObjectRegistry()
        reg.registration_hook(MyObj, 0)

        class MyNewerObj(object):
            VERSION = '1.123'

            @classmethod
            def obj_name(cls):
                return 'MyObj'

        self.assertEqual(MyObj, mock_objects.MyObj)
        reg.registration_hook(MyNewerObj, 0)
        self.assertEqual(MyNewerObj, mock_objects.MyObj)

    @mock.patch('ironic.objects.base.objects', autospec=True)
    def test_hook_keeps_newer_properly(self, mock_objects):
        reg = base.IronicObjectRegistry()
        reg.registration_hook(MyObj, 0)

        class MyOlderObj(object):
            VERSION = '1.1'

            @classmethod
            def obj_name(cls):
                return 'MyObj'

        self.assertEqual(MyObj, mock_objects.MyObj)
        reg.registration_hook(MyOlderObj, 0)
        self.assertEqual(MyObj, mock_objects.MyObj)


class TestMisc(test_base.TestCase):
    def test_max_version(self):
        versions = ['1.25', '1.33', '1.3']
        maxv = base.max_version(versions)
        self.assertEqual('1.33', maxv)

    def test_max_version_one(self):
        versions = ['1.25']
        maxv = base.max_version(versions)
        self.assertEqual('1.25', maxv)

    def test_max_version_two(self):
        versions = ['1.25', '1.26']
        maxv = base.max_version(versions)
        self.assertEqual('1.26', maxv)
