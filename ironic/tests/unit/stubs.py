# Copyright (c) 2011 Citrix Systems, Inc.
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

from glanceclient import exc as glance_exc


NOW_GLANCE_FORMAT = "2010-10-11T10:30:22"


class _GlanceWrapper(object):
    def __init__(self, wrapped):
        self.wrapped = wrapped

    def __iter__(self):
        return iter(())


class StubGlanceClient(object):

    fake_wrapped = object()

    def __init__(self, images=None):
        self._images = []
        _images = images or []
        map(lambda image: self.create(**image), _images)

        # NOTE(bcwaldon): HACK to get client.images.* to work
        self.images = lambda: None
        for fn in ('get', 'data'):
            setattr(self.images, fn, getattr(self, fn))

    def get(self, image_id):
        for image in self._images:
            if image.id == str(image_id):
                return image
        raise glance_exc.NotFound(image_id)

    def data(self, image_id):
        self.get(image_id)
        return _GlanceWrapper(self.fake_wrapped)


class FakeImage(dict):
    def __init__(self, metadata):
        IMAGE_ATTRIBUTES = ['size', 'disk_format', 'owner',
                            'container_format', 'checksum', 'id',
                            'name', 'deleted', 'status',
                            'min_disk', 'min_ram', 'tags', 'visibility',
                            'protected', 'file', 'schema', 'os_hash_algo',
                            'os_hash_value']
        raw = dict.fromkeys(IMAGE_ATTRIBUTES)
        raw.update(metadata)
        # raw['created_at'] = NOW_GLANCE_FORMAT
        # raw['updated_at'] = NOW_GLANCE_FORMAT
        super(FakeImage, self).__init__(raw)

    def __getattr__(self, key):
        try:
            return self[key]
        except KeyError:
            raise AttributeError(key)

    def __setattr__(self, key, value):
        if key in self:
            self[key] = value
        else:
            raise AttributeError(key)


class FakeNeutronPort(dict):
    def __init__(self, **attrs):
        PORT_ATTRS = ['admin_state_up',
                      'allowed_address_pairs',
                      'binding:host_id',
                      'binding:profile',
                      'binding:vif_details',
                      'binding:vif_type',
                      'binding:vnic_type',
                      'data_plane_status',
                      'description',
                      'device_id',
                      'device_owner',
                      'dns_assignment',
                      'dns_domain',
                      'dns_name',
                      'extra_dhcp_opts',
                      'fixed_ips',
                      'id',
                      'mac_address',
                      'name', 'network_id',
                      'port_security_enabled',
                      'security_group_ids',
                      'status',
                      'tenant_id',
                      'qos_network_policy_id',
                      'qos_policy_id',
                      'tags',
                      'uplink_status_propagation']

        raw = dict.fromkeys(PORT_ATTRS)
        raw.update(attrs)
        super(FakeNeutronPort, self).__init__(raw)

    def __getattr__(self, key):
        try:
            return self[key]
        except KeyError:
            raise AttributeError(key)

    def __setattr__(self, key, value):
        if key in self:
            self[key] = value
        else:
            raise AttributeError(key)


class FakeNeutronSubnet(dict):
    def __init__(self, **attrs):
        SUBNET_ATTRS = ['id',
                        'name',
                        'network_id',
                        'cidr',
                        'tenant_id',
                        'enable_dhcp',
                        'dns_nameservers',
                        'allocation_pools',
                        'host_routes',
                        'ip_version',
                        'gateway_ip',
                        'ipv6_address_mode',
                        'ipv6_ra_mode',
                        'subnetpool_id']

        raw = dict.fromkeys(SUBNET_ATTRS)
        raw.update(attrs)
        super(FakeNeutronSubnet, self).__init__(raw)

    def __getattr__(self, key):
        try:
            return self[key]
        except KeyError:
            raise AttributeError(key)

    def __setattr__(self, key, value):
        if key in self:
            self[key] = value
        else:
            raise AttributeError(key)


class FakeNeutronNetwork(dict):
    def __init__(self, **attrs):
        NETWORK_ATTRS = ['id',
                         'name',
                         'status',
                         'tenant_id',
                         'admin_state_up',
                         'segments',
                         'shared',
                         'subnets',
                         'provider:network_type',
                         'provider:physical_network',
                         'provider:segmentation_id',
                         'router:external',
                         'availability_zones',
                         'availability_zone_hints',
                         'is_default']

        raw = dict.fromkeys(NETWORK_ATTRS)
        raw.update(attrs)
        raw.update({
            'provider_physical_network': attrs.get(
                'provider:physical_network', None)})
        super(FakeNeutronNetwork, self).__init__(raw)

    def __getattr__(self, key):
        try:
            return self[key]
        except KeyError:
            raise AttributeError(key)

    def __setattr__(self, key, value):
        if key in self:
            self[key] = value
        else:
            raise AttributeError(key)


class FakeNeutronAgent(dict):
    def __init__(self, **attrs):
        AGENT_ATTRS = ['admin_state_up',
                       'agents',
                       'agent_type',
                       'alive',
                       'availability_zone',
                       'binary',
                       'configurations',
                       'created_at',
                       'description',
                       'heartbeat_timestamp',
                       'host',
                       'id',
                       'resources_synced',
                       'started_at',
                       'topic']

        raw = dict.fromkeys(AGENT_ATTRS)
        raw.update(attrs)
        raw.update({'is_alive': attrs.get('alive', False)})
        super(FakeNeutronAgent, self).__init__(raw)

    def __getattr__(self, key):
        try:
            return self[key]
        except KeyError:
            raise AttributeError(key)

    def __setattr__(self, key, value):
        if key in self:
            self[key] = value
        else:
            raise AttributeError(key)


class FakeNeutronSecurityGroup(dict):
    def __init__(self, **attrs):
        SECURITY_GROUP_ATTRS = ['id',
                                'name',
                                'description',
                                'stateful',
                                'project_id',
                                'tenant_id',
                                'security_group_rules']

        raw = dict.fromkeys(SECURITY_GROUP_ATTRS)
        raw.update(attrs)
        super(FakeNeutronSecurityGroup, self).__init__(raw)

    def __getattr__(self, key):
        try:
            return self[key]
        except KeyError:
            raise AttributeError(key)

    def __setattr__(self, key, value):
        if key in self:
            self[key] = value
        else:
            raise AttributeError(key)
