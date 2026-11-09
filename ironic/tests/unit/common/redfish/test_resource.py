# Copyright 2024 Red Hat, Inc.
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

"""Unit tests for lightweight async Redfish resource."""

import asyncio
from unittest import mock

from ironic.common.redfish import connector
from ironic.common.redfish import exceptions
from ironic.common.redfish import resource
from ironic.tests import base
from ironic.tests.unit.common.redfish import utils


class TestAsyncResource(base.TestCase):
    """Test AsyncResource class."""

    def setUp(self):
        super().setUp()
        self.mock_connector = mock.AsyncMock()
        self.path = '/redfish/v1/Systems/1'

    def test_init_with_data(self):
        """Test initialization with pre-fetched data."""
        data = {'Manufacturer': 'Dell', 'Model': 'PowerEdge'}
        res = resource.AsyncResource(self.mock_connector, self.path, data)

        self.assertEqual(self.path, res.path)
        self.assertEqual(data, res.json)

    def test_init_without_data(self):
        """Test initialization without data."""
        res = resource.AsyncResource(self.mock_connector, self.path)

        self.assertEqual(self.path, res.path)
        self.assertEqual({}, res.json)

    def test_refresh(self):
        """Test refreshing resource data."""
        data = {
            'Manufacturer': 'Dell',
            'Model': 'PowerEdge R640'
        }
        self.mock_connector.get = mock.AsyncMock(
            return_value=utils.json_response(data))

        res = resource.AsyncResource(self.mock_connector, self.path)

        async def run_test():
            result = await res.refresh()
            self.assertIs(result, res)  # Should return self
            self.assertEqual(data, res.json)
            self.mock_connector.get.assert_called_once_with(self.path)

        asyncio.run(run_test())

    def test_field_simple(self):
        """Test getting a simple field."""
        data = {
            'Manufacturer': 'Dell',
            'Model': 'PowerEdge',
            'SerialNumber': 'ABC123'
        }
        res = resource.AsyncResource(self.mock_connector, self.path, data)

        self.assertEqual('Dell', res.field('Manufacturer'))
        self.assertEqual('PowerEdge', res.field('Model'))
        self.assertEqual('ABC123', res.field('SerialNumber'))

    def test_field_nested(self):
        """Test getting nested fields with slash notation."""
        data = {
            'Boot': {
                'BootSourceOverrideTarget': 'Pxe',
                'BootSourceOverrideEnabled': 'Once'
            },
            'ProcessorSummary': {
                'Count': 2,
                'Model': 'Intel Xeon'
            }
        }
        res = resource.AsyncResource(self.mock_connector, self.path, data)

        self.assertEqual('Pxe', res.field('Boot/BootSourceOverrideTarget'))
        self.assertEqual('Once', res.field('Boot/BootSourceOverrideEnabled'))
        self.assertEqual(2, res.field('ProcessorSummary/Count'))
        self.assertEqual('Intel Xeon', res.field('ProcessorSummary/Model'))

    def test_field_not_found(self):
        """Test accessing non-existent field."""
        data = {'Manufacturer': 'Dell'}
        res = resource.AsyncResource(self.mock_connector, self.path, data)

        self.assertIsNone(res.field('NonExistent'))
        self.assertIsNone(res.field('Boot/BootTarget'))

    def test_field_with_default(self):
        """Test field with default value."""
        data = {'Manufacturer': 'Dell'}
        res = resource.AsyncResource(self.mock_connector, self.path, data)

        self.assertEqual('Unknown', res.field('Model', default='Unknown'))
        self.assertEqual(0, res.field('Count', default=0))

    def test_field_with_adapter(self):
        """Test field with adapter function."""
        data = {
            'PowerState': 'On',
            'PowerWatts': '450',
            'Count': '10'
        }
        res = resource.AsyncResource(self.mock_connector, self.path, data)

        # Adapter to convert to lowercase
        self.assertEqual('on', res.field('PowerState', adapter=str.lower))

        # Adapter to convert to int
        self.assertEqual(450, res.field('PowerWatts', adapter=int))
        self.assertEqual(10, res.field('Count', adapter=int))

    def test_field_with_adapter_error(self):
        """Test field with adapter that raises exception."""
        data = {'Value': 'not-a-number'}
        res = resource.AsyncResource(self.mock_connector, self.path, data)

        # Adapter fails, should return default
        self.assertIsNone(res.field('Value', adapter=int))
        self.assertEqual(0, res.field('Value', adapter=int, default=0))

    def test_action_success(self):
        """Test executing an action."""
        data = {
            'Actions': {
                '#ComputerSystem.Reset': {
                    'target': '/redfish/v1/Systems/1/Actions/'
                              'ComputerSystem.Reset',
                    'ResetType@Redfish.AllowableValues': ['On', 'ForceOff']
                }
            }
        }
        res = resource.AsyncResource(self.mock_connector, self.path, data)

        mock_response = mock.MagicMock()
        self.mock_connector.post = mock.AsyncMock(return_value=mock_response)

        async def run_test():
            payload = {'ResetType': 'ForceOff'}
            result = await res.action('ComputerSystem.Reset', payload)

            self.assertEqual(mock_response, result)
            self.mock_connector.post.assert_called_once_with(
                '/redfish/v1/Systems/1/Actions/ComputerSystem.Reset',
                data=payload
            )

        asyncio.run(run_test())

    def test_action_with_hash_prefix(self):
        """Test action with hash prefix in name."""
        data = {
            'Actions': {
                '#ComputerSystem.Reset': {
                    'target': '/redfish/v1/Systems/1/Actions/'
                              'ComputerSystem.Reset'
                }
            }
        }
        res = resource.AsyncResource(self.mock_connector, self.path, data)

        self.mock_connector.post = mock.AsyncMock()

        async def run_test():
            await res.action('#ComputerSystem.Reset', {'ResetType': 'On'})
            self.mock_connector.post.assert_called_once()

        asyncio.run(run_test())

    def test_action_not_found(self):
        """Test action that doesn't exist."""
        data = {'Actions': {}}
        res = resource.AsyncResource(self.mock_connector, self.path, data)

        async def run_test():
            try:
                await res.action('NonExistent', {})
                return None  # Should not reach here
            except ValueError as e:
                return e

        exception = asyncio.run(run_test())
        self.assertIsNotNone(exception)
        self.assertIsInstance(exception, ValueError)
        self.assertIn('not found', str(exception))

    def test_action_no_target(self):
        """Test action without target URL."""
        data = {
            'Actions': {
                '#SomeAction': {}
            }
        }
        res = resource.AsyncResource(self.mock_connector, self.path, data)

        async def run_test():
            try:
                await res.action('SomeAction', {})
                return None  # Should not reach here
            except ValueError as e:
                return e

        exception = asyncio.run(run_test())
        self.assertIsNotNone(exception)
        self.assertIsInstance(exception, ValueError)
        self.assertIn('no target', str(exception))

    def test_patch_simple(self):
        """Test PATCH operation."""
        data = {'AssetTag': 'old-tag'}
        res = resource.AsyncResource(self.mock_connector, self.path, data)

        mock_response = utils.json_response(None, status_code=204)

        self.mock_connector.patch = mock.AsyncMock(return_value=mock_response)
        self.mock_connector.get = mock.AsyncMock()

        async def run_test():
            payload = {'AssetTag': 'new-tag'}
            result = await res.patch(payload)

            self.assertEqual(mock_response, result)
            self.mock_connector.patch.assert_called_once_with(
                self.path,
                data=payload,
                etag=None
            )
            # A 204 carries nothing to adopt, and patch() does not read
            # the resource back, so the cached document is unchanged.
            self.assertEqual(data, res.json)
            self.mock_connector.get.assert_not_called()

        asyncio.run(run_test())

    def test_patch_with_etag(self):
        """Test PATCH with explicit ETag."""
        data = {'AssetTag': 'old-tag'}
        res = resource.AsyncResource(self.mock_connector, self.path, data)

        self.mock_connector.patch = mock.AsyncMock(
            return_value=utils.json_response(None, status_code=204))

        async def run_test():
            payload = {'AssetTag': 'new-tag'}
            await res.patch(payload, etag='W/"12345"')

            self.mock_connector.patch.assert_called_once_with(
                self.path,
                data=payload,
                etag='W/"12345"'
            )

        asyncio.run(run_test())

    def test_patch_with_cached_etag(self):
        """PATCH reuses the ETag captured by a real refresh().

        Regression test: refresh() used to discard the ETag, so patch()
        always sent etag=None and conditional updates could never work.
        The ETag must come from refresh(), not be set by hand.
        """
        data = {'AssetTag': 'old-tag'}
        res = resource.AsyncResource(self.mock_connector, self.path)

        self.mock_connector.patch = mock.AsyncMock(
            return_value=utils.json_response(None, status_code=204))
        self.mock_connector.get = mock.AsyncMock(
            return_value=utils.json_response(data, etag='W/"cached"'))

        async def run_test():
            await res.refresh()
            self.assertEqual('W/"cached"', res.etag)

            payload = {'AssetTag': 'new-tag'}
            await res.patch(payload)

            self.mock_connector.patch.assert_called_once_with(
                self.path,
                data=payload,
                etag='W/"cached"'
            )

        asyncio.run(run_test())

    @mock.patch.object(resource, 'LOG', autospec=True)
    def test_patch_masks_password_in_debug_log(self, mock_log):
        """patch() must not leak secrets into the debug log.

        The payload still reaches the connector verbatim; only the log
        record is sanitized.
        """
        res = resource.AsyncResource(self.mock_connector, self.path, {})

        self.mock_connector.patch = mock.AsyncMock(
            return_value=utils.json_response(None, status_code=204))

        async def run_test():
            payload = {'UserName': 'admin', 'Password': 's3cr3t'}
            await res.patch(payload)

            self.mock_connector.patch.assert_called_once_with(
                self.path, data=payload, etag=None)

            # check every debug record rather than just the last one.
            logged = str(mock_log.debug.call_args_list)
            self.assertNotIn('s3cr3t', logged)
            self.assertIn('***', logged)

        asyncio.run(run_test())

    @mock.patch.object(resource, 'LOG', autospec=True)
    def test_action_masks_password_in_debug_log(self, mock_log):
        """action() must not leak secrets into the debug log.

        InsertMedia carries the credentials for the media server, so an
        unsanitized payload would write them to the log verbatim.
        """
        data = {
            'Actions': {
                '#VirtualMedia.InsertMedia': {
                    'target': '/redfish/v1/Managers/1/VM1/Actions/'
                              'VirtualMedia.InsertMedia'
                }
            }
        }
        res = resource.AsyncResource(self.mock_connector, self.path, data)
        self.mock_connector.post = mock.AsyncMock()

        async def run_test():
            payload = {'Image': 'http://example.com/boot.iso',
                       'UserName': 'admin',
                       'Password': 's3cr3t'}
            await res.action('VirtualMedia.InsertMedia', payload)

            # The real request is unaffected by sanitization.
            self.mock_connector.post.assert_called_once_with(
                data['Actions']['#VirtualMedia.InsertMedia']['target'],
                data=payload)

            logged = str(mock_log.debug.call_args)
            self.assertNotIn('s3cr3t', logged)
            self.assertIn('***', logged)

        asyncio.run(run_test())

    def test_refresh_captures_etag(self):
        """refresh() stores the ETag header for conditional updates."""
        data = {'AssetTag': 'old-tag'}
        res = resource.AsyncResource(self.mock_connector, self.path)
        self.mock_connector.get = mock.AsyncMock(
            return_value=utils.json_response(data, etag='"strong-etag"'))

        async def run_test():
            await res.refresh()
            self.assertEqual('"strong-etag"', res.etag)
            self.assertEqual(data, res.json)

        asyncio.run(run_test())

    def test_refresh_without_etag_header(self):
        """A response with no ETag header leaves the cached ETag unset."""
        res = resource.AsyncResource(self.mock_connector, self.path)
        self.mock_connector.get = mock.AsyncMock(
            return_value=utils.json_response({'AssetTag': 'tag'}))

        async def run_test():
            await res.refresh()
            self.assertIsNone(res.etag)

        asyncio.run(run_test())

    def test_patch_takes_the_etag_from_its_own_response(self):
        """The ETag is replaced by the one the PATCH response carries.

        patch() no longer reads the resource back, so the new ETag has
        to come from the PATCH response itself or the next conditional
        update would send the superseded one.
        """
        res = resource.AsyncResource(self.mock_connector, self.path)

        self.mock_connector.patch = mock.AsyncMock(
            return_value=utils.json_response(
                None, status_code=204, etag='W/"second"'))
        self.mock_connector.get = mock.AsyncMock(
            return_value=utils.json_response({'AssetTag': 'old'},
                                             etag='W/"first"'))

        async def run_test():
            await res.refresh()
            await res.patch({'AssetTag': 'new'})

            self.mock_connector.patch.assert_called_once_with(
                self.path, data={'AssetTag': 'new'}, etag='W/"first"')
            self.assertEqual('W/"second"', res.etag)

        asyncio.run(run_test())

    def test_patch_forgets_a_superseded_etag(self):
        """Without a new ETag the old one must be dropped, not kept.

        The document it described no longer exists, so reusing it as
        If-Match earns a 412 on the next update.
        """
        res = resource.AsyncResource(self.mock_connector, self.path)

        self.mock_connector.patch = mock.AsyncMock(
            return_value=utils.json_response(None, status_code=204))
        self.mock_connector.get = mock.AsyncMock(
            return_value=utils.json_response({'AssetTag': 'old'},
                                             etag='W/"first"'))

        async def run_test():
            await res.refresh()
            self.assertEqual('W/"first"', res.etag)

            await res.patch({'AssetTag': 'new'})
            self.assertIsNone(res.etag)

            await res.patch({'AssetTag': 'newer'})
            self.assertEqual(
                mock.call(self.path, data={'AssetTag': 'newer'}, etag=None),
                self.mock_connector.patch.call_args)

        asyncio.run(run_test())

    def test_refresh_malformed_json(self):
        """A body that cannot be parsed raises MalformedAttributeError."""
        res = resource.AsyncResource(self.mock_connector, self.path)
        response = utils.json_response({})
        response.json.side_effect = ValueError('not json')
        self.mock_connector.get = mock.AsyncMock(return_value=response)

        async def run_test():
            try:
                await res.refresh()
            except exceptions.MalformedAttributeError as e:
                return e

        self.assertIsInstance(asyncio.run(run_test()),
                              exceptions.MalformedAttributeError)

    def test_link_simple(self):
        """Test following a simple link."""
        data = {
            'Bios': {
                '@odata.id': '/redfish/v1/Systems/1/Bios'
            }
        }
        res = resource.AsyncResource(self.mock_connector, self.path, data)

        bios_data = {'BootMode': 'Uefi'}
        self.mock_connector.get = mock.AsyncMock(
            return_value=utils.json_response(bios_data))

        async def run_test():
            bios = await res.link('Bios')

            self.assertIsInstance(bios, resource.AsyncResource)
            self.assertEqual('/redfish/v1/Systems/1/Bios', bios.path)
            self.assertEqual(bios_data, bios.json)

        asyncio.run(run_test())

    def test_link_in_links_object(self):
        """Test following a link in the Links object."""
        data = {
            'Links': {
                'Chassis': [
                    {'@odata.id': '/redfish/v1/Chassis/1'}
                ]
            }
        }
        res = resource.AsyncResource(self.mock_connector, self.path, data)

        async def run_test():
            # This will return an AsyncResourceCollection
            chassis_collection = await res.link('Chassis')

            self.assertIsInstance(
                chassis_collection, resource.AsyncResourceCollection)
            self.assertEqual(1, len(chassis_collection))

        asyncio.run(run_test())

    def test_link_not_found(self):
        """Test link that doesn't exist."""
        data = {'Bios': {'@odata.id': '/redfish/v1/Systems/1/Bios'}}
        res = resource.AsyncResource(self.mock_connector, self.path, data)

        async def run_test():
            try:
                await res.link('NonExistent')
                return None  # Should not reach here
            except ValueError as e:
                return e

        exception = asyncio.run(run_test())
        self.assertIsNotNone(exception)
        self.assertIsInstance(exception, ValueError)
        self.assertIn('not found', str(exception))

    def test_collection_links(self):
        """Test getting all members from a collection."""
        data = {
            'Members': [
                {'@odata.id': '/redfish/v1/Systems/1'},
                {'@odata.id': '/redfish/v1/Systems/2'}
            ]
        }
        res = resource.AsyncResource(self.mock_connector, self.path, data)

        system1_data = {'Manufacturer': 'Dell'}
        system2_data = {'Manufacturer': 'HPE'}

        self.mock_connector.get = mock.AsyncMock(
            side_effect=[utils.json_response(system1_data),
                         utils.json_response(system2_data)]
        )

        async def run_test():
            systems = await res.collection('Members').get_all()

            self.assertEqual(2, len(systems))
            self.assertEqual(system1_data, systems[0].json)
            self.assertEqual(system2_data, systems[1].json)

        asyncio.run(run_test())

    def test_collection_links_empty(self):
        """Test collection with no members."""
        data = {'Members': []}
        res = resource.AsyncResource(self.mock_connector, self.path, data)

        async def run_test():
            systems = await res.collection('Members').get_all()
            self.assertEqual(0, len(systems))

        asyncio.run(run_test())

    def test_refresh_with_expand(self):
        """Test refreshing resource data with $expand."""
        data = {'Id': '1', 'Thermal': {'Fans': []}}
        self.mock_connector.get = mock.AsyncMock(
            return_value=utils.json_response(data))

        res = resource.AsyncResource(self.mock_connector, self.path)

        async def run_test():
            result = await res.refresh(expand=True)
            self.assertIs(result, res)
            self.assertEqual(data, res.json)
            expected_path = self.path + '?$expand=.($levels=1)'
            self.mock_connector.get.assert_called_once_with(expected_path)

        asyncio.run(run_test())

    def test_refresh_without_expand(self):
        """Test that refresh without expand uses the plain path."""
        data = {'Id': '1'}
        self.mock_connector.get = mock.AsyncMock(
            return_value=utils.json_response(data))

        res = resource.AsyncResource(self.mock_connector, self.path)

        async def run_test():
            await res.refresh(expand=False)
            self.mock_connector.get.assert_called_once_with(self.path)

        asyncio.run(run_test())

    def test_link_with_expand(self):
        """Test following a link with $expand."""
        data = {
            'Storage': {
                '@odata.id': '/redfish/v1/Systems/1/Storage'
            }
        }
        res = resource.AsyncResource(self.mock_connector, self.path, data)

        storage_data = {'Members': []}
        self.mock_connector.get = mock.AsyncMock(
            return_value=utils.json_response(storage_data))

        async def run_test():
            storage = await res.link('Storage', expand=True)

            self.assertIsInstance(storage, resource.AsyncResource)
            self.assertEqual('/redfish/v1/Systems/1/Storage', storage.path)
            expected_path = (
                '/redfish/v1/Systems/1/Storage?$expand=.($levels=1)')
            self.mock_connector.get.assert_called_once_with(expected_path)

        asyncio.run(run_test())

    def test_link_without_expand(self):
        """Test following a link without $expand uses plain path."""
        data = {
            'Bios': {
                '@odata.id': '/redfish/v1/Systems/1/Bios'
            }
        }
        res = resource.AsyncResource(self.mock_connector, self.path, data)

        bios_data = {'BootMode': 'Uefi'}
        self.mock_connector.get = mock.AsyncMock(
            return_value=utils.json_response(bios_data))

        async def run_test():
            await res.link('Bios', expand=False)
            self.mock_connector.get.assert_called_once_with(
                '/redfish/v1/Systems/1/Bios')

        asyncio.run(run_test())

    def test_link_collection_with_expand(self):
        """Test following a collection link with $expand."""
        data = {
            'Links': {
                'Chassis': [
                    {'@odata.id': '/redfish/v1/Chassis/1'},
                    {'@odata.id': '/redfish/v1/Chassis/2'},
                ]
            }
        }
        res = resource.AsyncResource(self.mock_connector, self.path, data)

        async def run_test():
            chassis_collection = await res.link('Chassis', expand=True)

            self.assertIsInstance(
                chassis_collection, resource.AsyncResourceCollection)
            self.assertEqual(2, len(chassis_collection))
            expected_paths = [
                '/redfish/v1/Chassis/1?$expand=.($levels=1)',
                '/redfish/v1/Chassis/2?$expand=.($levels=1)',
            ]
            self.assertEqual(expected_paths, chassis_collection.paths)

        asyncio.run(run_test())

    def test_collection_with_expand(self):
        """Test getting a collection with $expand on member paths."""
        data = {
            'Members': [
                {'@odata.id': '/redfish/v1/Systems/1'},
                {'@odata.id': '/redfish/v1/Systems/2'}
            ]
        }
        res = resource.AsyncResource(self.mock_connector, self.path, data)

        collection = res.collection('Members', expand=True)
        expected_paths = [
            '/redfish/v1/Systems/1?$expand=.($levels=1)',
            '/redfish/v1/Systems/2?$expand=.($levels=1)',
        ]
        self.assertEqual(expected_paths, collection.paths)

    def test_collection_without_expand(self):
        """Test that collection without expand uses plain paths."""
        data = {
            'Members': [
                {'@odata.id': '/redfish/v1/Systems/1'},
                {'@odata.id': '/redfish/v1/Systems/2'}
            ]
        }
        res = resource.AsyncResource(self.mock_connector, self.path, data)

        collection = res.collection('Members', expand=False)
        expected_paths = [
            '/redfish/v1/Systems/1',
            '/redfish/v1/Systems/2',
        ]
        self.assertEqual(expected_paths, collection.paths)

    def test_repr(self):
        """Test string representation."""
        res = resource.AsyncResource(self.mock_connector, self.path)
        self.assertEqual(f"AsyncResource(path={self.path!r})", repr(res))


class TestAsyncResourceCollection(base.TestCase):
    """Test AsyncResourceCollection class."""

    def setUp(self):
        super().setUp()
        self.mock_connector = mock.AsyncMock()
        self.paths = [
            '/redfish/v1/Systems/1',
            '/redfish/v1/Systems/2',
            '/redfish/v1/Systems/3'
        ]

    def test_init(self):
        """Test initialization."""
        collection = resource.AsyncResourceCollection(
            self.mock_connector,
            self.paths
        )

        self.assertEqual(3, len(collection))

    def test_get_all(self):
        """Test fetching all resources."""
        data1 = {'Manufacturer': 'Dell'}
        data2 = {'Manufacturer': 'HPE'}
        data3 = {'Manufacturer': 'Lenovo'}

        self.mock_connector.get = mock.AsyncMock(
            side_effect=[utils.json_response(data1),
                         utils.json_response(data2),
                         utils.json_response(data3)]
        )

        collection = resource.AsyncResourceCollection(
            self.mock_connector,
            self.paths
        )

        async def run_test():
            resources = await collection.get_all()

            self.assertEqual(3, len(resources))
            self.assertEqual(data1, resources[0].json)
            self.assertEqual(data2, resources[1].json)
            self.assertEqual(data3, resources[2].json)

        asyncio.run(run_test())

    def test_get_by_index(self):
        """Test fetching a single resource by index."""
        data = {'Manufacturer': 'HPE'}
        self.mock_connector.get = mock.AsyncMock(
            return_value=utils.json_response(data))

        collection = resource.AsyncResourceCollection(
            self.mock_connector,
            self.paths
        )

        async def run_test():
            resource_obj = await collection.get(1)

            self.assertEqual(data, resource_obj.json)
            self.assertEqual(self.paths[1], resource_obj.path)

        asyncio.run(run_test())

    def test_get_index_out_of_range(self):
        """Test getting resource with invalid index."""
        collection = resource.AsyncResourceCollection(
            self.mock_connector,
            self.paths
        )

        async def run_test():
            try:
                await collection.get(10)
                return None  # Should not reach here
            except IndexError as e:
                return e

        exception = asyncio.run(run_test())
        self.assertIsNotNone(exception)
        self.assertIsInstance(exception, IndexError)

    def test_repr(self):
        """Test string representation."""
        collection = resource.AsyncResourceCollection(
            self.mock_connector,
            self.paths
        )
        self.assertEqual('AsyncResourceCollection(count=3)', repr(collection))

    def test_one_success(self):
        """Test one() with exactly one resource."""
        data = {'Manufacturer': 'Dell', 'Model': 'PowerEdge R640'}
        self.mock_connector.get = mock.AsyncMock(
            return_value=utils.json_response(data))

        single_path = ['/redfish/v1/Systems/1']
        collection = resource.AsyncResourceCollection(
            self.mock_connector,
            single_path
        )

        async def run_test():
            resource_obj = await collection.one()

            self.assertEqual(data, resource_obj.json)
            self.assertEqual(single_path[0], resource_obj.path)

        asyncio.run(run_test())

    def test_one_empty_collection(self):
        """Test one() with empty collection."""
        collection = resource.AsyncResourceCollection(
            self.mock_connector,
            []
        )

        async def run_test():
            try:
                await collection.one()
                return None  # Should not reach here
            except exceptions.UnknownDefaultError as e:
                return e

        exception = asyncio.run(run_test())
        self.assertIsNotNone(exception)
        self.assertIsInstance(exception, exceptions.UnknownDefaultError)
        self.assertIn('found 0', str(exception))

    def test_one_multiple_resources(self):
        """Test one() with multiple resources."""
        collection = resource.AsyncResourceCollection(
            self.mock_connector,
            self.paths
        )

        async def run_test():
            try:
                await collection.one()
                return None  # Should not reach here
            except exceptions.UnknownDefaultError as e:
                return e

        exception = asyncio.run(run_test())
        self.assertIsNotNone(exception)
        self.assertIsInstance(exception, exceptions.UnknownDefaultError)
        self.assertIn('found 3', str(exception))


class TestResourceConnectorContract(base.TestCase):
    """Pin the contract between AsyncConnector and AsyncResource.

    Mocking the connector hides whether what it really returns matches
    what AsyncResource expects, which is how the dropped ETag went
    unnoticed: get() returned a parsed dict, so refresh() never saw any
    headers. These tests drive a real AsyncConnector with only the httpx
    transport mocked.
    """

    def setUp(self):
        super().setUp()
        self.path = '/redfish/v1/Systems/1'

    @staticmethod
    def _mock_client(body, headers):
        class FakeResponse:
            status_code = 200

            def __init__(self):
                self.headers = headers

            def json(self):
                return body

            def raise_for_status(self):
                pass

        class MockAsyncClient:
            def __init__(self, *args, **kwargs):
                self.auth = None
                self.headers = {}

            async def request(self, *args, **kwargs):
                return FakeResponse()

            async def aclose(self):
                pass

        return MockAsyncClient

    def _refresh(self, body, headers):
        client = self._mock_client(body, headers)

        async def run_test():
            with mock.patch('httpx.AsyncClient', client):
                async with connector.AsyncConnector('https://bmc') as conn:
                    res = resource.AsyncResource(conn, self.path)
                    await res.refresh()
                    return res

        return asyncio.run(run_test())

    def test_refresh_captures_etag_through_real_connector(self):
        """The ETag survives the trip from the connector to the resource."""
        body = {'AssetTag': 'tag'}
        res = self._refresh(body, {'ETag': 'W/"from-bmc"'})

        self.assertEqual('W/"from-bmc"', res.etag)
        self.assertEqual(body, res.json)

    def test_refresh_no_etag_through_real_connector(self):
        """No ETag header means no cached ETag, and no crash."""
        res = self._refresh({'AssetTag': 'tag'}, {})

        self.assertIsNone(res.etag)
        self.assertEqual({'AssetTag': 'tag'}, res.json)


class TestExpandQueryNormalisation(base.TestCase):
    """The expand query is a request detail, not part of the path.

    collection() and link() hand it to every member path, so without
    normalisation it reached places it has no business being: the PATCH
    target, repr(), and a second copy of itself when an already-expanded
    resource was refreshed with expand=True.
    """

    def setUp(self):
        super().setUp()
        self.mock_connector = mock.AsyncMock()
        self.path = '/redfish/v1/Systems/1'
        self.expanded_path = self.path + resource.EXPAND_QUERY

    def test_plain_path_is_not_expanded(self):
        res = resource.AsyncResource(self.mock_connector, self.path)

        self.assertEqual(self.path, res.path)
        self.assertFalse(res.expanded)

    def test_expand_query_is_stripped_and_remembered(self):
        res = resource.AsyncResource(self.mock_connector, self.expanded_path)

        self.assertEqual(self.path, res.path)
        self.assertTrue(res.expanded)

    def test_repr_shows_the_clean_path(self):
        res = resource.AsyncResource(self.mock_connector, self.expanded_path)

        self.assertEqual(f"AsyncResource(path={self.path!r})", repr(res))

    def test_refresh_does_not_append_a_second_expand_query(self):
        """Regression: the query was appended to a path that had it."""
        self.mock_connector.get = mock.AsyncMock(
            return_value=utils.json_response({'Id': '1'}))
        res = resource.AsyncResource(self.mock_connector, self.expanded_path)

        async def run_test():
            await res.refresh(expand=True)

        asyncio.run(run_test())

        self.mock_connector.get.assert_called_once_with(self.expanded_path)

    def test_refresh_defaults_to_the_expansion_it_was_built_with(self):
        """An expanded resource stays expanded across a bare refresh()."""
        self.mock_connector.get = mock.AsyncMock(
            return_value=utils.json_response({'Id': '1'}))
        res = resource.AsyncResource(self.mock_connector, self.expanded_path)

        async def run_test():
            await res.refresh()

        asyncio.run(run_test())

        self.mock_connector.get.assert_called_once_with(self.expanded_path)

    def test_refresh_false_overrides_and_sticks(self):
        """An explicit False wins over the path, and stays the default."""
        self.mock_connector.get = mock.AsyncMock(
            return_value=utils.json_response({'Id': '1'}))
        res = resource.AsyncResource(self.mock_connector, self.expanded_path)

        async def run_test():
            await res.refresh(expand=False)
            await res.refresh()

        asyncio.run(run_test())

        self.assertFalse(res.expanded)
        self.assertEqual([mock.call(self.path)] * 2,
                         self.mock_connector.get.call_args_list)

    def test_refresh_true_overrides_and_sticks(self):
        """So does an explicit True, for a resource built without it."""
        self.mock_connector.get = mock.AsyncMock(
            return_value=utils.json_response({'Id': '1'}))
        res = resource.AsyncResource(self.mock_connector, self.path)

        async def run_test():
            await res.refresh(expand=True)
            await res.refresh()

        asyncio.run(run_test())

        self.assertTrue(res.expanded)
        self.assertEqual([mock.call(self.expanded_path)] * 2,
                         self.mock_connector.get.call_args_list)

    def test_patch_targets_the_clean_path(self):
        """Regression: PATCH went to the URL with the expand query on it."""
        self.mock_connector.patch = mock.AsyncMock(
            return_value=utils.json_response(None, status_code=204))
        res = resource.AsyncResource(self.mock_connector, self.expanded_path)

        async def run_test():
            await res.patch({'AssetTag': 'new'})

        asyncio.run(run_test())

        self.mock_connector.patch.assert_called_once_with(
            self.path, data={'AssetTag': 'new'}, etag=None)

    def test_action_target_is_unaffected(self):
        """Actions use the target from the body, never the resource path."""
        target = '/redfish/v1/Systems/1/Actions/ComputerSystem.Reset'
        data = {'Actions': {'#ComputerSystem.Reset': {'target': target}}}
        self.mock_connector.post = mock.AsyncMock()
        res = resource.AsyncResource(
            self.mock_connector, self.expanded_path, data)

        async def run_test():
            await res.action('ComputerSystem.Reset', {'ResetType': 'On'})

        asyncio.run(run_test())

        self.mock_connector.post.assert_called_once_with(
            target, data={'ResetType': 'On'})

    def test_expanded_collection_members_are_normalised(self):
        """The end-to-end path: collection(expand=True) to a member."""
        data = {'Members': [{'@odata.id': '/redfish/v1/Systems/1'}]}
        parent = resource.AsyncResource(self.mock_connector, '/redfish/v1'
                                        '/Systems', data)
        self.mock_connector.get = mock.AsyncMock(
            return_value=utils.json_response({'Id': '1'}))

        async def run_test():
            return await parent.collection('Members', expand=True).one()

        member = asyncio.run(run_test())

        # the member knows it is expanded, but holds a path it can PATCH
        self.assertEqual('/redfish/v1/Systems/1', member.path)
        self.assertTrue(member.expanded)
        self.mock_connector.get.assert_called_once_with(
            '/redfish/v1/Systems/1' + resource.EXPAND_QUERY)


class TestPatchDoesNotReadBack(base.TestCase):
    """A PATCH that worked must not be reported as having failed.

    patch() used to GET the resource immediately afterwards. A BMC that
    is still applying the change can answer that GET with a 5xx, which
    propagated out of patch() and left the caller unable to tell a
    rejected update from an applied one.
    """

    def setUp(self):
        super().setUp()
        self.mock_connector = mock.AsyncMock()
        self.path = '/redfish/v1/Systems/1'
        self.before = {'@odata.id': '/redfish/v1/Systems/1',
                       'AssetTag': 'old'}

    def _patch(self, response):
        res = resource.AsyncResource(
            self.mock_connector, self.path, dict(self.before))
        self.mock_connector.patch = mock.AsyncMock(return_value=response)

        async def run_test():
            return await res.patch({'AssetTag': 'new'})

        return res, asyncio.run(run_test())

    def test_a_failing_read_back_cannot_mask_a_good_patch(self):
        self.mock_connector.get = mock.AsyncMock(
            side_effect=exceptions.ServerSideError(
                'GET', self.path,
                utils.json_response({'error': 'still settling'},
                                    status_code=500)))

        res, response = self._patch(
            utils.json_response(None, status_code=204))

        self.assertEqual(204, response.status_code)
        self.assertEqual(self.before, res.json)
        self.mock_connector.get.assert_not_called()

    def test_returned_representation_is_adopted(self):
        """A BMC that answers with the new body saves the caller a GET."""
        after = {'@odata.id': '/redfish/v1/Systems/1', 'AssetTag': 'new'}

        res, _ = self._patch(utils.json_response(after))

        self.assertEqual(after, res.json)
        self.assertEqual('new', res.field('AssetTag'))

    def test_message_body_is_not_adopted_as_the_resource(self):
        """A 200 may carry an outcome message rather than the resource.

        Adopting it would leave field() answering with defaults for a
        resource that is perfectly healthy, which is worse than keeping
        a document known to be one update out of date.
        """
        message = {
            '@Message.ExtendedInfo': [{'MessageId': 'Base.1.0.Success'}]}

        res, _ = self._patch(utils.json_response(message))

        self.assertEqual(self.before, res.json)

    def test_non_dict_body_is_not_adopted(self):
        res, _ = self._patch(utils.json_response(['not', 'a', 'resource']))

        self.assertEqual(self.before, res.json)

    def test_unparseable_body_is_not_adopted(self):
        response = utils.json_response({'ignored': True})
        response.json.side_effect = ValueError('no JSON here')

        res, _ = self._patch(response)

        self.assertEqual(self.before, res.json)

    def test_empty_body_is_not_adopted(self):
        res, _ = self._patch(utils.json_response(None, status_code=204))

        self.assertEqual(self.before, res.json)
