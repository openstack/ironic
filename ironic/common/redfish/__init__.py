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

"""Async Redfish client for Ironic.

A lightweight asynchronous Redfish client built on httpx with dynamic
resource access. Provides async/await patterns for interacting with
Redfish resources.

Example usage::

    from ironic.common import redfish

    async with redfish.AsyncRedfishClient(
        'https://bmc.example.com',
        username='admin',
        password='password',
        auth_type='auto'
    ) as client:
        # Get the only system (when you know there's exactly one)
        systems = await client.collection('Systems')
        system = await systems.one()
        print(f"Manufacturer: {system.field('Manufacturer')}")
        print(f"Power state: {system.field('PowerState')}")

        # Get all systems in a collection
        systems = await client.collection('Systems')
        for system in await systems.get_all():
            print(f"System: {system.field('Name')}")

        # Get resources by name
        update_service = await client.resource('UpdateService')
        print(f"Enabled: {update_service.field('ServiceEnabled')}")

        # Get resources by absolute path
        bios = await client.resource('/redfish/v1/Systems/1/Bios')
        print(f"Boot mode: {bios.field('BootMode')}")
"""

from ironic.common.redfish.auth import AsyncBasicAuth
from ironic.common.redfish.auth import AsyncSessionAuth
from ironic.common.redfish.auth import AsyncSessionOrBasicAuth
from ironic.common.redfish.client import AsyncRedfishClient
from ironic.common.redfish.connector import AsyncConnector
from ironic.common.redfish import exceptions
from ironic.common.redfish.resource import AsyncResource
from ironic.common.redfish.resource import AsyncResourceCollection
from ironic.common.redfish.taskmonitor import AsyncTaskMonitor

__all__ = [
    'AsyncRedfishClient',
    'AsyncConnector',
    'AsyncBasicAuth',
    'AsyncSessionAuth',
    'AsyncSessionOrBasicAuth',
    'AsyncResource',
    'AsyncResourceCollection',
    'AsyncTaskMonitor',
    'exceptions',
]
