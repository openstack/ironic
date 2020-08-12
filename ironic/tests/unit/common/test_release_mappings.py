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

from unittest import mock

from oslo_utils import versionutils

from ironic.api.controllers.v1 import versions as api_versions
from ironic.common import release_mappings
from ironic.conductor import rpcapi
from ironic.db.sqlalchemy import models
from ironic.objects import base as obj_base
from ironic.tests import base


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
    """Tests the dict release_mappings.RELEASE_MAPPING.

    Tests whether the dict release_mappings.RELEASE_MAPPING is correct,
    valid and consistent.
    """
    def test_structure(self):
        for value in release_mappings.RELEASE_MAPPING.values():
            self.assertIsInstance(value, dict)
            self.assertEqual({'api', 'rpc', 'objects'}, set(value))
            self.assertIsInstance(value['api'], str)
            (major, minor) = value['api'].split('.')
            self.assertEqual(1, int(major))
            self.assertLessEqual(int(minor), api_versions.MINOR_MAX_VERSION)
            self.assertIsInstance(value['rpc'], str)
            self.assertIsInstance(value['objects'], dict)
            for obj_value in value['objects'].values():
                self.assertIsInstance(obj_value, list)
                for ver in obj_value:
                    self.assertIsInstance(ver, str)
                    tuple_ver = versionutils.convert_version_to_tuple(ver)
                    self.assertEqual(2, len(tuple_ver))

    def test_object_names_are_registered(self):
        registered_objects = set(obj_base.IronicObjectRegistry.obj_classes())
        for mapping in release_mappings.RELEASE_MAPPING.values():
            objects = set(mapping['objects'])
            self.assertTrue(objects.issubset(registered_objects))

    def test_current_rpc_version(self):
        self.assertEqual(rpcapi.ConductorAPI.RPC_API_VERSION,
                         release_mappings.RELEASE_MAPPING['master']['rpc'])

    def test_current_object_versions(self):
        registered_objects = obj_base.IronicObjectRegistry.obj_classes()
        obj_versions = release_mappings.get_object_versions(
            releases=['master'])
        for obj, vers in obj_versions.items():
            # vers is a set of versions, not ordered
            self.assertIn(registered_objects[obj][0].VERSION, vers)

    def test_contains_all_db_objects(self):
        self.assertIn('master', release_mappings.RELEASE_MAPPING)
        model_names = set((s.__name__ for s in models.Base.__subclasses__()))
        exceptions = set(['NodeTag', 'ConductorHardwareInterfaces',
                          'NodeTrait', 'BIOSSetting', 'DeployTemplateStep'])
        # NOTE(xek): As a rule, all models which can be changed between
        # releases or are sent through RPC should have their counterpart
        # versioned objects.
        model_names -= exceptions
        # NodeTrait maps to two objects
        model_names |= set(['Trait', 'TraitList'])
        # Deployment is purely virtual.
        model_names.add('Deployment')
        object_names = set(
            release_mappings.RELEASE_MAPPING['master']['objects'])
        self.assertEqual(model_names, object_names)

    def test_rpc_and_objects_versions_supported(self):
        registered_objects = obj_base.IronicObjectRegistry.obj_classes()
        for versions in release_mappings.RELEASE_MAPPING.values():
            self.assertTrue(_check_versions_compatibility(
                versions['rpc'], rpcapi.ConductorAPI.RPC_API_VERSION))
            for obj_name, obj_vers in versions['objects'].items():
                for ver in obj_vers:
                    self.assertTrue(_check_versions_compatibility(
                        ver, registered_objects[obj_name][0].VERSION))


class GetObjectVersionsTestCase(base.TestCase):

    TEST_MAPPING = {
        '7.0': {
            'api': '1.30',
            'rpc': '1.40',
            'objects': {
                'Node': ['1.21'],
                'Conductor': ['1.2'],
                'Port': ['1.6'],
                'Portgroup': ['1.3'],
            }
        },
        '8.0': {
            'api': '1.30',
            'rpc': '1.40',
            'objects': {
                'Node': ['1.22'],
                'Conductor': ['1.2'],
                'Chassis': ['1.3'],
                'Port': ['1.6'],
                'Portgroup': ['1.5', '1.4'],
            }
        },
        'master': {
            'api': '1.34',
            'rpc': '1.40',
            'objects': {
                'Node': ['1.23'],
                'Conductor': ['1.2'],
                'Chassis': ['1.3'],
                'Port': ['1.7'],
                'Portgroup': ['1.5'],
            }
        },
    }
    TEST_MAPPING['ocata'] = TEST_MAPPING['7.0']

    def test_get_object_versions(self):
        with mock.patch.dict(release_mappings.RELEASE_MAPPING,
                             self.TEST_MAPPING, clear=True):
            actual_versions = release_mappings.get_object_versions()
            expected_versions = {
                'Node': set(['1.21', '1.22', '1.23']),
                'Conductor': set(['1.2']),
                'Chassis': set(['1.3']),
                'Port': set(['1.6', '1.7']),
                'Portgroup': set(['1.3', '1.4', '1.5']),
            }
            self.assertEqual(expected_versions, actual_versions)

    def test_get_object_versions_releases(self):
        with mock.patch.dict(release_mappings.RELEASE_MAPPING,
                             self.TEST_MAPPING, clear=True):
            actual_versions = release_mappings.get_object_versions(
                releases=['ocata'])
            expected_versions = {
                'Node': set(['1.21']),
                'Conductor': set(['1.2']),
                'Port': set(['1.6']),
                'Portgroup': set(['1.3']),
            }
            self.assertEqual(expected_versions, actual_versions)

    def test_get_object_versions_objects(self):
        with mock.patch.dict(release_mappings.RELEASE_MAPPING,
                             self.TEST_MAPPING, clear=True):
            actual_versions = release_mappings.get_object_versions(
                objects=['Portgroup', 'Chassis'])
            expected_versions = {
                'Portgroup': set(['1.3', '1.4', '1.5']),
                'Chassis': set(['1.3']),
            }
            self.assertEqual(expected_versions, actual_versions)

    def test_get_object_versions_releases_objects(self):
        with mock.patch.dict(release_mappings.RELEASE_MAPPING,
                             self.TEST_MAPPING, clear=True):
            actual_versions = release_mappings.get_object_versions(
                releases=['7.0'], objects=['Portgroup', 'Chassis'])
            expected_versions = {
                'Portgroup': set(['1.3']),
            }
            self.assertEqual(expected_versions, actual_versions)
