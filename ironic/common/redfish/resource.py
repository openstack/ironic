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

"""Lightweight asynchronous Redfish resource implementation."""

from oslo_log import log

from ironic.common.redfish import exceptions
from sushy import utils


LOG = log.getLogger(__name__)

EXPAND_QUERY = '?$expand=.($levels=1)'


def _representation(response):
    """Return the resource document a PATCH response carries, if any.

    A Redfish PATCH may answer with the updated resource, with
    ``204 No Content``, or with a message object describing the outcome.
    Only the first is usable as the new resource state, and it is told
    apart by the ``@odata.id`` every representation carries: adopting a
    message object instead would silently empty the resource.

    :param response: Response returned by the connector.
    :returns: The parsed document, or None if there is nothing usable.
    """
    if not getattr(response, 'content', None):
        return None

    try:
        body = response.json()
    except Exception as e:
        LOG.debug('PATCH response body could not be parsed as JSON, '
                  'leaving the cached resource data alone: %(error)s',
                  {'error': e})
        return None

    if isinstance(body, dict) and '@odata.id' in body:
        return body
    return None


class AsyncResource:
    """Lightweight asynchronous Redfish resource.

    This is a dynamic alternative to sushy's static field-based resources.
    Instead of declaring all fields upfront, it provides methods to access
    fields, execute actions, and navigate links on-demand.

    Example usage::

        system = AsyncResource(connector, '/redfish/v1/Systems/1')
        await system.refresh()

        # Get simple fields
        manufacturer = system.field('Manufacturer')

        # Get nested fields with slash notation
        boot_target = system.field('Boot/BootSourceOverrideTarget')

        # Apply adapters to field values
        power_state = system.field('PowerState', adapter=str.lower)

        # Execute actions
        await system.action('Reset', {'ResetType': 'ForceRestart'})

        # PATCH resources
        await system.patch({'AssetTag': 'new-tag'})

        # Navigate to subresources
        bios = await system.link('Bios')
        boot_mode = bios.field('BootMode')
    """

    def __init__(self, connector, path, json_data=None):
        """Initialize an AsyncResource.

        :param connector: AsyncConnector instance for HTTP operations
        :param path: Resource path (e.g., '/redfish/v1/Systems/1'). A
                     trailing ``?$expand=.($levels=1)`` is stripped off and
                     remembered, so the resource keeps a clean path to PATCH
                     against and refreshes itself expanded by default.
        :param json_data: Optional pre-fetched JSON data. If not provided,
                         call refresh() to fetch it.
        """
        self._connector = connector
        # collection() and link() append the expand query to every member
        # path, so strip it back off and remember it instead: left in the
        # path it would leak into the PATCH target and into repr(), and
        # refresh(expand=True) would append a second copy.
        self._path = path.removesuffix(EXPAND_QUERY)
        self._expanded = self._path != path
        self._json = json_data or {}
        self._etag = None

    async def refresh(self, expand=None):
        """Refresh the resource data from the server.

        :param expand: Whether to request ``$expand=.($levels=1)`` so that
            sub-resources are fetched inline (mirrors sushy's ``_expanded``
            properties). ``None``, the default, keeps whatever this resource
            was built with, so a member of a collection taken with
            ``expand=True`` stays expanded when it is refreshed. ``True`` or
            ``False`` override that and become the resource's new default,
            keeping ``expanded`` in step with the document in ``json``.
        :returns: self for method chaining
        """
        if expand is None:
            expand = self._expanded
        else:
            self._expanded = expand

        path = self._path
        if expand:
            path = f'{path}{EXPAND_QUERY}'

        LOG.debug('Refreshing resource at %(path)s', {'path': path})

        response = await self._connector.get(path)

        try:
            self._json = response.json()
        except Exception as e:
            LOG.error('Failed to parse JSON response from %(path)s: '
                      '%(error)s', {'path': path, 'error': e})
            raise exceptions.MalformedAttributeError(
                attribute='response body', resource=path, error=e)

        # Capture the ETag so patch() can issue conditional updates. Like
        # sushy, only the header is consulted.
        self._etag = response.headers.get('ETag')

        return self

    def field(self, name, adapter=None, default=None):
        """Get a field value from the resource JSON.

        Supports nested field access using slash notation.

        :param name: Field name or path (e.g., 'Manufacturer' or
                    'Boot/BootSourceOverrideTarget')
        :param adapter: Optional callable to process the field value
        :param default: Default value if field is not found
        :returns: Field value, optionally processed by adapter

        Example:
            manufacturer = resource.field('Manufacturer')
            boot_target = resource.field('Boot/BootSourceOverrideTarget')
            power_watts = resource.field('PowerWatts', adapter=int)
        """
        # Navigate through nested fields
        parts = name.split('/')
        value = self._json

        for part in parts:
            if not isinstance(value, dict):
                return default
            value = value.get(part)
            if value is None:
                return default

        # Apply adapter if provided
        if adapter is not None and value is not None:
            try:
                return adapter(value)
            except (ValueError, TypeError) as e:
                LOG.warning('Failed to apply adapter to field %(field)s: '
                            '%(error)s',
                            {'field': name, 'error': e})
                return default

        return value

    async def action(self, name, payload=None):
        """Execute a Redfish action on this resource.

        :param name: Action name (e.g., 'Reset', 'ComputerSystem.Reset')
        :param payload: Optional dict payload for the action
        :returns: Response from the action POST request
        :raises: ValueError if action is not found or has no target

        Example::

            await system.action('Reset', {'ResetType': 'ForceRestart'})
            payload = {'Image': 'http://example.com/image.iso'}
            await virtual_media.action('InsertMedia', payload)

        """
        actions = self._json.get('Actions', {})

        # Try with and without the hash prefix
        action_key = name if name.startswith('#') else f'#{name}'
        action_info = actions.get(action_key)

        if action_info is None:
            # Try without hash prefix
            action_info = actions.get(name)

        if action_info is None:
            raise ValueError(
                f"Action '{name}' not found in resource at {self._path}")

        target = action_info.get('target')
        if not target:
            raise ValueError(f"Action '{name}' has no target URL")

        LOG.debug('Executing action %(action)s on %(path)s with payload '
                  '%(payload)s',
                  {'action': name, 'path': self._path,
                   'payload': utils.sanitize(payload)})

        return await self._connector.post(target, data=payload or {})

    async def patch(self, payload, etag=None):
        """PATCH this resource with the given payload.

        The resource is deliberately *not* re-fetched afterwards. A BMC
        that is still settling after an update can answer the follow-up
        GET with a 5xx, and raising that here would report a PATCH that
        in fact succeeded as a failure, leaving the caller unable to tell
        the two apart. Instead, when the BMC returns the updated
        representation in the PATCH response it is adopted directly --
        the same shortcut sushy takes with ``refresh(json_doc=...)``.
        Otherwise ``json`` keeps the pre-PATCH document, and a caller
        that needs the new state calls ``refresh()`` itself, where a
        failure is unambiguously a failure to read.

        :param payload: Dict of fields to update
        :param etag: Optional ETag for conditional updates. If not provided,
                    uses the ETag from the last refresh (if available)
        :returns: Response from the PATCH request

        Example:
            await system.patch({'AssetTag': 'new-tag'})
            await system.patch({'Boot': {'BootSourceOverrideTarget': 'Pxe'}})
        """
        # Use provided ETag or fall back to cached one
        etag_to_use = etag or self._etag

        LOG.debug('Patching resource at %(path)s with payload %(payload)s',
                  {'path': self._path, 'payload': utils.sanitize(payload)})

        response = await self._connector.patch(
            self._path,
            data=payload,
            etag=etag_to_use
        )

        # The resource has just changed, so the cached ETag no longer
        # describes it. Take the new one if the BMC sent it, otherwise
        # forget it: no If-Match at all beats a stale one that earns a
        # 412 on the next conditional update.
        self._etag = response.headers.get('ETag')

        updated = _representation(response)
        if updated is not None:
            LOG.debug('Adopting the representation returned by PATCH of '
                      '%(path)s', {'path': self._path})
            self._json = updated

        return response

    async def link(self, name, default=..., expand=False):
        """Get a linked subresource.

        Navigates to a linked resource via @odata.id reference.
        Supports links in the 'Links' object or as direct properties.

        :param name: Link name (e.g., 'Bios', 'Storage', 'Processors')
        :param default: Default value if link is not found (defaults to raising
                       ValueError)
        :param expand: If True, fetch the linked resource with
            ``$expand=.($levels=1)`` to inline sub-resources in a single
            request. Mirrors sushy's ``chassis_expanded`` /
            ``storage_expanded`` properties.
        :returns: AsyncResource instance for the linked resource, or default
        :raises: ValueError if link is not found and no default provided

        Example::

            bios = await system.link('Bios')
            boot_mode = bios.field('BootMode')

            storage_collection = await system.link('Storage', expand=True)
            members = storage_collection.field('Members', default=[])

            # Optional link that may not exist
            thermal = await chassis.link('Thermal', default=None)
            if thermal:
                fans = thermal.field('Fans', default=[])
        """
        # Check in Links object first
        links = self._json.get('Links', {})
        link_data = links.get(name)

        # Fall back to direct property
        if link_data is None:
            link_data = self._json.get(name)

        if link_data is None:
            if default is not ...:
                return default
            raise ValueError(
                f"Link '{name}' not found in resource at {self._path}")

        # Extract @odata.id from the link
        if isinstance(link_data, dict):
            odata_id = link_data.get('@odata.id')
            if odata_id:
                LOG.debug('Following link %(name)s to %(target)s',
                          {'name': name, 'target': odata_id})
                resource = AsyncResource(self._connector, odata_id)
                await resource.refresh(expand=expand)
                return resource

        # Handle collection links (list of references)
        if isinstance(link_data, list):
            if link_data and isinstance(link_data[0], dict):
                first_id = link_data[0].get('@odata.id')
                if first_id:
                    paths = [
                        item.get('@odata.id') for item in link_data
                        if isinstance(item, dict) and '@odata.id' in item
                    ]
                    if expand:
                        paths = [f'{p}{EXPAND_QUERY}' for p in paths]
                    return AsyncResourceCollection(
                        self._connector, paths
                    )

        if default is not ...:
            return default
        raise ValueError(
            f"Link '{name}' does not contain a valid @odata.id reference"
        )

    def collection(self, name='Members', expand=False):
        """Get a collection of resources from a collection field.

        :param name: Collection field name (e.g., 'Members', 'Drives')
        :param expand: If True, append ``$expand=.($levels=1)`` to each
            member path so sub-resources are fetched inline when the
            collection is iterated. Each member strips the query back off
            in ``AsyncResource.__init__``, so it never reaches a PATCH
            target and is never appended twice.
        :returns: AsyncResourceCollection instance

        Example::

            # Get all systems from a collection
            systems_collection_resource = await client.resource(
                '/redfish/v1/Systems'
            )
            systems_collection = systems_collection_resource.collection()
            systems = await systems_collection.get_all()
            for system in systems:
                print(system.field('Manufacturer'))

            # Get all drives from a storage resource with expansion
            storage = await client.resource('/redfish/v1/Systems/1/Storage/1')
            drives_collection = storage.collection('Drives', expand=True)
            drives = await drives_collection.get_all()

        """
        # NOTE(iurygregory): Only the members in the response already held
        # are returned. We don't follow ``Members@odata.nextLink``, this
        # matches sushy, which doesn't follow the Link either.
        members = self.field(name, default=[])

        paths = []
        for member in members:
            if isinstance(member, dict):
                odata_id = member.get('@odata.id')
                if odata_id:
                    paths.append(odata_id)

        if expand:
            paths = [f'{p}{EXPAND_QUERY}' for p in paths]

        return AsyncResourceCollection(self._connector, paths)

    @property
    def path(self):
        """Get the resource path."""
        return self._path

    @property
    def json(self):
        """Get the raw JSON data."""
        return self._json

    @property
    def etag(self):
        """Get the cached ETag value."""
        return self._etag

    @property
    def expanded(self):
        """Whether this resource is fetched with ``$expand`` by default."""
        return self._expanded

    def __repr__(self):
        return f"AsyncResource(path={self._path!r})"


class AsyncResourceCollectionIterator:
    """Iterator for AsyncResourceCollection.

    Holds iteration state separately from the collection,
    allowing the same collection to be iterated multiple times.
    """

    def __init__(self, connector, paths):
        """Initialize the iterator.

        :param connector: AsyncConnector instance
        :param paths: List of resource paths
        """
        self._connector = connector
        self._paths = paths
        self._index = 0

    def __aiter__(self):
        """Return self as the iterator."""
        return self

    async def __anext__(self):
        """Get next resource in the collection.

        :returns: AsyncResource instance with refreshed data
        :raises: StopAsyncIteration when no more resources
        """
        if self._index >= len(self._paths):
            raise StopAsyncIteration

        path = self._paths[self._index]
        self._index += 1

        resource = AsyncResource(self._connector, path)
        await resource.refresh()
        return resource


class AsyncResourceCollection:
    """Helper for working with collections of resources.

    This is returned when accessing collection links that contain
    multiple @odata.id references.

    Supports async iteration:
        async for resource in collection:
            print(resource.field('Name'))

    Can be iterated multiple times:
        async for resource in collection:
            # First iteration
        async for resource in collection:
            # Second iteration (independent)
    """

    def __init__(self, connector, paths):
        """Initialize a collection.

        :param connector: AsyncConnector instance
        :param paths: List of resource paths
        """
        self._connector = connector
        self._paths = paths

    @property
    def paths(self):
        """Returns a list of all paths in the collection."""
        return list(self._paths)

    def __aiter__(self):
        """Return a new async iterator.

        This allows: async for resource in collection
        Creates a new iterator each time, allowing multiple iterations.
        """
        return AsyncResourceCollectionIterator(self._connector, self._paths)

    async def get_all(self):
        """Fetch all resources in the collection.

        :returns: List of AsyncResource instances with refreshed data
        """
        resources = []
        async for resource in self:
            resources.append(resource)
        return resources

    async def get(self, index):
        """Get a single resource by index.

        :param index: Index in the collection
        :returns: AsyncResource instance with refreshed data
        """
        if 0 <= index < len(self._paths):
            resource = AsyncResource(self._connector, self._paths[index])
            await resource.refresh()
            return resource
        raise IndexError(f"Collection index {index} out of range")

    async def one(self):
        """Get the single resource from this collection.

        :returns: AsyncResource instance with refreshed data
        :raises: UnknownDefaultError if collection doesn't have exactly 1 item

        Example:
            # Get the only system (useful when you know there's exactly one)
            systems = await client.collection('Systems')
            system = await systems.one()
        """
        count = len(self._paths)
        if count != 1:
            raise exceptions.UnknownDefaultError(count=count)

        resource = AsyncResource(self._connector, self._paths[0])
        await resource.refresh()
        return resource

    def __len__(self):
        return len(self._paths)

    def __repr__(self):
        return f"AsyncResourceCollection(count={len(self._paths)})"
