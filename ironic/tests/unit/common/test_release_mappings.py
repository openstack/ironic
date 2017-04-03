#    Copyright 2016 Intel Corp.
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

from oslo_utils import versionutils
import six

from ironic.common.release_mappings import RELEASE_MAPPING
from ironic.conductor import rpcapi
from ironic.db.sqlalchemy import models
from ironic.objects import base as obj_base
from ironic.tests import base
from ironic import version


def _check_versions_compatibility(conf_version, actual_version):
    """Checks the configured version against the actual version.

    Returns True if the configured version is <= the actual version;
    otherwise returns False.

    :param conf_version: configured version, a string with dots
    :param actual_version: actual version, a string with dots
    :returns: True if the configured version is <= the actual version;
              False otherwise.
    """
    conf_cap = versionutils.convert_version_to_tuple(conf_version)
    actual_cap = versionutils.convert_version_to_tuple(actual_version)
    return conf_cap <= actual_cap


class ReleaseMappingsTestCase(base.TestCase):
    """Tests whether the dict RELEASE_MAPPING is correct, valid and consistent.

    """
    def test_structure(self):
        for value in RELEASE_MAPPING.values():
            self.assertTrue(isinstance(value, dict))
            self.assertEqual({'rpc', 'objects'}, set(value))
            self.assertTrue(isinstance(value['rpc'], six.string_types))
            self.assertTrue(isinstance(value['objects'], dict))
            for obj_value in value['objects'].values():
                self.assertTrue(isinstance(obj_value, six.string_types))
                tuple_ver = versionutils.convert_version_to_tuple(obj_value)
                self.assertEqual(2, len(tuple_ver))

    def test_object_names_are_registered(self):
        registered_objects = set(obj_base.IronicObjectRegistry.obj_classes())
        for mapping in RELEASE_MAPPING.values():
            objects = set(mapping['objects'])
            self.assertTrue(objects.issubset(registered_objects))

    def test_contains_current_release_entry(self):
        version_info = str(version.version_info)
        # NOTE(sborkows): We only need first two values from version (like 5.1)
        # and assume version_info is of the form 'x.y.z'.
        current_release = version_info[:version_info.rfind('.')]
        self.assertIn(current_release, RELEASE_MAPPING)

    def test_current_rpc_version(self):
        self.assertEqual(rpcapi.ConductorAPI.RPC_API_VERSION,
                         RELEASE_MAPPING['master']['rpc'])

    def test_current_object_versions(self):
        registered_objects = obj_base.IronicObjectRegistry.obj_classes()
        for obj, objver in RELEASE_MAPPING['master']['objects'].items():
            self.assertEqual(registered_objects[obj][0].VERSION, objver)

    def test_contains_all_db_objects(self):
        self.assertIn('master', RELEASE_MAPPING)
        model_names = set((s.__name__ for s in models.Base.__subclasses__()))
        exceptions = set(['NodeTag', 'ConductorHardwareInterfaces'])
        # NOTE(xek): As a rule, all models which can be changed between
        # releases or are sent through RPC should have their counterpart
        # versioned objects.
        model_names -= exceptions
        object_names = set(RELEASE_MAPPING['master']['objects'])
        self.assertEqual(model_names, object_names)

    def test_rpc_and_objects_versions_supported(self):
        registered_objects = obj_base.IronicObjectRegistry.obj_classes()
        for versions in RELEASE_MAPPING.values():
            self.assertTrue(_check_versions_compatibility(
                versions['rpc'], rpcapi.ConductorAPI.RPC_API_VERSION))
            for obj_name, obj_ver in versions['objects'].items():
                self.assertTrue(_check_versions_compatibility(
                    obj_ver, registered_objects[obj_name][0].VERSION))
