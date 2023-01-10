# Copyright 2013 Hewlett-Packard Development Company, L.P.
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
"""Ironic test utilities."""


from oslo_utils import timeutils
from oslo_utils import uuidutils

from ironic.common import states
from ironic.db import api as db_api
from ironic.drivers import base as drivers_base
from ironic.objects import allocation
from ironic.objects import bios
from ironic.objects import chassis
from ironic.objects import conductor
from ironic.objects import deploy_template
from ironic.objects import node
from ironic.objects import node_history
from ironic.objects import node_inventory
from ironic.objects import port
from ironic.objects import portgroup
from ironic.objects import trait
from ironic.objects import volume_connector
from ironic.objects import volume_target


def get_test_ipmi_info():
    return {
        "ipmi_address": "1.2.3.4",
        "ipmi_username": "admin",
        "ipmi_password": "fake"
    }


def get_test_ipmi_bridging_parameters():
    return {
        "ipmi_bridging": "dual",
        "ipmi_local_address": "0x20",
        "ipmi_transit_channel": "0",
        "ipmi_transit_address": "0x82",
        "ipmi_target_channel": "7",
        "ipmi_target_address": "0x72"
    }


def get_test_pxe_driver_info():
    return {
        "deploy_kernel": "glance://deploy_kernel_uuid",
        "deploy_ramdisk": "glance://deploy_ramdisk_uuid",
        "rescue_kernel": "glance://rescue_kernel_uuid",
        "rescue_ramdisk": "glance://rescue_ramdisk_uuid"
    }


def get_test_pxe_driver_internal_info():
    return {
        "is_whole_disk_image": False,
    }


def get_test_pxe_instance_info():
    return {
        "image_source": "glance://image_uuid",
        "root_gb": 100,
        "rescue_password": "password"
    }


def get_test_ilo_info():
    return {
        "ilo_address": "1.2.3.4",
        "ilo_username": "admin",
        "ilo_password": "fake",
    }


def get_test_drac_info():
    return {
        "drac_address": "1.2.3.4",
        "drac_port": 443,
        "drac_path": "/wsman",
        "drac_protocol": "https",
        "drac_username": "admin",
        "drac_password": "fake",
        "redfish_address": "1.2.3.4",
        "redfish_system_id": "/redfish/v1/Systems/System.Embedded.1",
        "redfish_username": "admin",
        "redfish_password": "fake"
    }


def get_test_irmc_info():
    return {
        "irmc_address": "1.2.3.4",
        "irmc_username": "admin0",
        "irmc_password": "fake0",
        "irmc_port": "80",
        "irmc_auth_method": "digest",
    }


def get_test_agent_instance_info():
    return {
        'image_source': 'fake-image',
        'image_url': 'http://image',
        'image_checksum': 'checksum',
        'image_disk_format': 'qcow2',
        'image_container_format': 'bare',
    }


def get_test_agent_driver_info():
    return {
        'deploy_kernel': 'glance://deploy_kernel_uuid',
        'deploy_ramdisk': 'glance://deploy_ramdisk_uuid',
        'ipmi_password': 'foo',
    }


def get_test_agent_driver_internal_info():
    return {
        'agent_url': 'http://127.0.0.1/foo',
        'is_whole_disk_image': True,
    }


def get_test_snmp_info(**kw):
    result = {
        "snmp_driver": kw.get("snmp_driver", "teltronix"),
        "snmp_address": kw.get("snmp_address", "1.2.3.4"),
        "snmp_port": kw.get("snmp_port", "161"),
        "snmp_outlet": kw.get("snmp_outlet", "1"),
        "snmp_version": kw.get("snmp_version", "1")
    }
    if result["snmp_version"] in ("1", "2c"):
        result["snmp_community"] = kw.get("snmp_community", "public")
        if "snmp_community_read" in kw:
            result["snmp_community_read"] = kw["snmp_community_read"]
        if "snmp_community_write" in kw:
            result["snmp_community_write"] = kw["snmp_community_write"]
    elif result["snmp_version"] == "3":
        result["snmp_user"] = kw.get(
            "snmp_user", kw.get("snmp_security", "snmpuser")
        )
        for option in ('snmp_auth_protocol', 'snmp_auth_key',
                       'snmp_priv_protocol', 'snmp_priv_key',
                       'snmp_context_engine_id', 'snmp_context_name'):
            if option in kw:
                result[option] = kw[option]
    return result


def get_test_node(**kw):
    properties = {
        "cpu_arch": "x86_64",
        "cpus": "8",
        "local_gb": "10",
        "memory_mb": "4096",
    }
    # NOTE(tenbrae): API unit tests confirm that sensitive fields in
    #                instance_info and driver_info will get scrubbed
    #                from the API response but other fields
    #                (eg, 'foo') do not.
    fake_instance_info = {
        "configdrive": "TG9yZW0gaXBzdW0gZG9sb3Igc2l0IGFtZXQ=",
        "image_url": "http://example.com/test_image_url",
        "foo": "bar",
    }
    fake_driver_info = {
        "foo": "bar",
        "fake_password": "fakepass",
    }
    fake_internal_info = {
        "private_state": "secret value"
    }
    result = {
        'version': kw.get('version', node.Node.VERSION),
        'id': kw.get('id', 123),
        'name': kw.get('name', None),
        'uuid': kw.get('uuid', '1be26c0b-03f2-4d2e-ae87-c02d7f33c123'),
        'chassis_id': kw.get('chassis_id', None),
        'conductor_affinity': kw.get('conductor_affinity', None),
        'conductor_group': kw.get('conductor_group', ''),
        'power_state': kw.get('power_state', states.NOSTATE),
        'target_power_state': kw.get('target_power_state', states.NOSTATE),
        'provision_state': kw.get('provision_state', states.AVAILABLE),
        'target_provision_state': kw.get('target_provision_state',
                                         states.NOSTATE),
        'provision_updated_at': kw.get('provision_updated_at'),
        'last_error': kw.get('last_error'),
        'instance_uuid': kw.get('instance_uuid'),
        'instance_info': kw.get('instance_info', fake_instance_info),
        'driver': kw.get('driver', 'fake-hardware'),
        'driver_info': kw.get('driver_info', fake_driver_info),
        'driver_internal_info': kw.get('driver_internal_info',
                                       fake_internal_info),
        'clean_step': kw.get('clean_step'),
        'deploy_step': kw.get('deploy_step'),
        'properties': kw.get('properties', properties),
        'reservation': kw.get('reservation'),
        'maintenance': kw.get('maintenance', False),
        'maintenance_reason': kw.get('maintenance_reason'),
        'fault': kw.get('fault'),
        'console_enabled': kw.get('console_enabled', False),
        'extra': kw.get('extra', {}),
        'updated_at': kw.get('updated_at'),
        'created_at': kw.get('created_at'),
        'inspection_finished_at': kw.get('inspection_finished_at'),
        'inspection_started_at': kw.get('inspection_started_at'),
        'raid_config': kw.get('raid_config'),
        'target_raid_config': kw.get('target_raid_config'),
        'tags': kw.get('tags', []),
        'resource_class': kw.get('resource_class'),
        'traits': kw.get('traits', []),
        'automated_clean': kw.get('automated_clean', None),
        'protected': kw.get('protected', False),
        'protected_reason': kw.get('protected_reason', None),
        'conductor': kw.get('conductor'),
        'owner': kw.get('owner', None),
        'allocation_id': kw.get('allocation_id'),
        'description': kw.get('description'),
        'retired': kw.get('retired', False),
        'retired_reason': kw.get('retired_reason', None),
        'lessee': kw.get('lessee', None),
        'network_data': kw.get('network_data'),
        'boot_mode': kw.get('boot_mode', None),
        'secure_boot': kw.get('secure_boot', None),
    }

    for iface in drivers_base.ALL_INTERFACES:
        name = '%s_interface' % iface
        result[name] = kw.get(name)

    return result


def create_test_node(**kw):
    """Create test node entry in DB and return Node DB object.

    Function to be used to create test Node objects in the database.

    :param kw: kwargs with overriding values for node's attributes.
    :returns: Test Node DB object.

    """
    node = get_test_node(**kw)
    # Let DB generate an ID if one isn't specified explicitly.
    # Creating a node with tags or traits will raise an exception. If tags or
    # traits are not specified explicitly just delete them.
    for field in {'id', 'tags', 'traits'}:
        if field not in kw:
            del node[field]
    dbapi = db_api.get_instance()
    return dbapi.create_node(node)


def get_test_port(**kw):
    return {
        'id': kw.get('id', 987),
        'version': kw.get('version', port.Port.VERSION),
        'uuid': kw.get('uuid', '1be26c0b-03f2-4d2e-ae87-c02d7f33c781'),
        'node_id': kw.get('node_id', 123),
        'node_uuid': kw.get('node_uuid',
                            '59d102f7-5840-4299-8ec8-80c0ebae9de1'),
        'address': kw.get('address', '52:54:00:cf:2d:31'),
        'extra': kw.get('extra', {}),
        'created_at': kw.get('created_at'),
        'updated_at': kw.get('updated_at'),
        'local_link_connection': kw.get('local_link_connection',
                                        {'switch_id': '0a:1b:2c:3d:4e:5f',
                                         'port_id': 'Ethernet3/1',
                                         'switch_info': 'switch1'}),
        'portgroup_id': kw.get('portgroup_id'),
        'pxe_enabled': kw.get('pxe_enabled', True),
        'internal_info': kw.get('internal_info', {"bar": "buzz"}),
        'physical_network': kw.get('physical_network'),
        'is_smartnic': kw.get('is_smartnic', False),
        'name': kw.get('name'),
    }


def create_test_port(**kw):
    """Create test port entry in DB and return Port DB object.

    Function to be used to create test Port objects in the database.

    :param kw: kwargs with overriding values for port's attributes.
    :returns: Test Port DB object.

    """
    port = get_test_port(**kw)
    # Let DB generate ID if it isn't specified explicitly
    if 'id' not in kw:
        del port['id']
    dbapi = db_api.get_instance()
    return dbapi.create_port(port)


def get_test_volume_connector(**kw):
    return {
        'id': kw.get('id', 789),
        'version': kw.get('version', volume_connector.VolumeConnector.VERSION),
        'uuid': kw.get('uuid', '1be26c0b-03f2-4d2e-ae87-c02d7f33c781'),
        'node_id': kw.get('node_id', 123),
        'type': kw.get('type', 'iqn'),
        'connector_id': kw.get('connector_id',
                               'iqn.2012-06.com.example:initiator'),
        'extra': kw.get('extra', {}),
        'created_at': kw.get('created_at'),
        'updated_at': kw.get('updated_at'),
    }


def create_test_volume_connector(**kw):
    """Create test connector entry in DB and return VolumeConnector DB object.

    Function to be used to create test VolumeConnector objects in the database.

    :param kw: kwargs with overriding values for connector's attributes.
    :returns: Test VolumeConnector DB object.

    """
    connector = get_test_volume_connector(**kw)
    # Let DB generate ID if it isn't specified explicitly
    if 'id' not in kw:
        del connector['id']
    dbapi = db_api.get_instance()
    return dbapi.create_volume_connector(connector)


def get_test_volume_target(**kw):
    fake_properties = {"target_iqn": "iqn.foo"}
    return {
        'id': kw.get('id', 789),
        'version': kw.get('version', volume_target.VolumeTarget.VERSION),
        'uuid': kw.get('uuid', '1be26c0b-03f2-4d2e-ae87-c02d7f33c781'),
        'node_id': kw.get('node_id', 123),
        'volume_type': kw.get('volume_type', 'iscsi'),
        'properties': kw.get('properties', fake_properties),
        'boot_index': kw.get('boot_index', 0),
        'volume_id': kw.get('volume_id', '12345678'),
        'extra': kw.get('extra', {}),
        'created_at': kw.get('created_at'),
        'updated_at': kw.get('updated_at'),
    }


def create_test_volume_target(**kw):
    """Create test target entry in DB and return VolumeTarget DB object.

    Function to be used to create test VolumeTarget objects in the database.

    :param kw: kwargs with overriding values for target's attributes.
    :returns: Test VolumeTarget DB object.

    """
    target = get_test_volume_target(**kw)
    # Let DB generate ID if it isn't specified explicitly
    if 'id' not in kw:
        del target['id']
    dbapi = db_api.get_instance()
    return dbapi.create_volume_target(target)


def get_test_chassis(**kw):
    return {
        'id': kw.get('id', 42),
        'version': kw.get('version', chassis.Chassis.VERSION),
        'uuid': kw.get('uuid', 'e74c40e0-d825-11e2-a28f-0800200c9a66'),
        'extra': kw.get('extra', {}),
        'description': kw.get('description', 'data-center-1-chassis'),
        'created_at': kw.get('created_at'),
        'updated_at': kw.get('updated_at'),
    }


def create_test_chassis(**kw):
    """Create test chassis entry in DB and return Chassis DB object.

    Function to be used to create test Chassis objects in the database.

    :param kw: kwargs with overriding values for chassis's attributes.
    :returns: Test Chassis DB object.

    """
    chassis = get_test_chassis(**kw)
    # Let DB generate ID if it isn't specified explicitly
    if 'id' not in kw:
        del chassis['id']
    dbapi = db_api.get_instance()
    return dbapi.create_chassis(chassis)


def get_test_conductor(**kw):
    return {
        'id': kw.get('id', 6),
        'version': kw.get('version', conductor.Conductor.VERSION),
        'hostname': kw.get('hostname', 'test-conductor-node'),
        'drivers': kw.get('drivers', ['fake-driver', 'null-driver']),
        'conductor_group': kw.get('conductor_group', ''),
        'created_at': kw.get('created_at', timeutils.utcnow()),
        'updated_at': kw.get('updated_at', timeutils.utcnow()),
    }


def create_test_conductor(**kw):
    """Create test conductor entry in DB and return Conductor DB object.

    Function to be used to create test Conductor objects in the database.

    :param kw: kwargs with overriding values for conductor's attributes.
    :returns: Test Conductor DB object.

    """
    conductor = get_test_conductor(**kw)
    # Let DB generate ID if it isn't specified explicitly
    if 'id' not in kw:
        del conductor['id']
    dbapi = db_api.get_instance()
    return dbapi.register_conductor(conductor)


def get_test_redfish_info():
    return {
        "redfish_address": "https://example.com",
        "redfish_system_id": "/redfish/v1/Systems/FAKESYSTEM",
        "redfish_username": "username",
        "redfish_password": "password"
    }


def get_test_portgroup(**kw):
    return {
        'id': kw.get('id', 654),
        'version': kw.get('version', portgroup.Portgroup.VERSION),
        'uuid': kw.get('uuid', '6eb02b44-18a3-4659-8c0b-8d2802581ae4'),
        'name': kw.get('name', 'fooname'),
        'node_id': kw.get('node_id', 123),
        'address': kw.get('address', '52:54:00:cf:2d:31'),
        'extra': kw.get('extra', {}),
        'created_at': kw.get('created_at'),
        'updated_at': kw.get('updated_at'),
        'internal_info': kw.get('internal_info', {"bar": "buzz"}),
        'standalone_ports_supported': kw.get('standalone_ports_supported',
                                             True),
        'mode': kw.get('mode'),
        'properties': kw.get('properties', {}),
    }


def create_test_portgroup(**kw):
    """Create test portgroup entry in DB and return Portgroup DB object.

    Function to be used to create test Portgroup objects in the database.

    :param kw: kwargs with overriding values for port's attributes.
    :returns: Test Portgroup DB object.

    """
    portgroup = get_test_portgroup(**kw)
    # Let DB generate ID if it isn't specified explicitly
    if 'id' not in kw:
        del portgroup['id']
    dbapi = db_api.get_instance()
    return dbapi.create_portgroup(portgroup)


def get_test_node_tag(**kw):
    return {
        # TODO(rloo): Replace None below with the object NodeTag VERSION,
        #             after this lands: https://review.opendev.org/#/c/233357
        'version': kw.get('version', None),
        "tag": kw.get("tag", "tag1"),
        "node_id": kw.get("node_id", "123"),
        'created_at': kw.get('created_at'),
        'updated_at': kw.get('updated_at'),
    }


def create_test_node_tag(**kw):
    """Create test node tag entry in DB and return NodeTag DB object.

    Function to be used to create test NodeTag objects in the database.

    :param kw: kwargs with overriding values for tag's attributes.
    :returns: Test NodeTag DB object.

    """
    tag = get_test_node_tag(**kw)
    dbapi = db_api.get_instance()
    return dbapi.add_node_tag(tag['node_id'], tag['tag'])


def get_test_xclarity_properties():
    return {
        "cpu_arch": "x86_64",
        "cpus": "8",
        "local_gb": "10",
        "memory_mb": "4096",
    }


def get_test_xclarity_driver_info():
    return {
        'xclarity_manager_ip': "1.2.3.4",
        'xclarity_username': "USERID",
        'xclarity_password': "fake",
        'xclarity_port': 443,
        'xclarity_hardware_id': 'fake_sh_id',
    }


def get_test_node_trait(**kw):
    return {
        'version': kw.get('version', trait.Trait.VERSION),
        "trait": kw.get("trait", "trait1"),
        "node_id": kw.get("node_id", "123"),
        'created_at': kw.get('created_at'),
        'updated_at': kw.get('updated_at'),
    }


def create_test_node_trait(**kw):
    """Create test node trait entry in DB and return NodeTrait DB object.

    Function to be used to create test NodeTrait objects in the database.

    :param kw: kwargs with overriding values for trait's attributes.
    :returns: Test NodeTrait DB object.
    """
    trait = get_test_node_trait(**kw)
    dbapi = db_api.get_instance()
    return dbapi.add_node_trait(trait['node_id'], trait['trait'],
                                trait['version'])


def create_test_node_traits(traits, **kw):
    """Create test node trait entries in DB and return NodeTrait DB objects.

    Function to be used to create test NodeTrait objects in the database.

    :param traits: a list of Strings; traits to create.
    :param kw: kwargs with overriding values for trait's attributes.
    :returns: a list of test NodeTrait DB objects.
    """
    return [create_test_node_trait(trait=trait, **kw) for trait in traits]


def create_test_bios_setting(**kw):
    """Create test bios entry in DB and return BIOSSetting DB object.

    Function to be used to create test BIOSSetting object in the database.

    :param kw: kwargs with overriding values for node bios settings.
    :returns: Test BIOSSetting DB object.

    """
    bios_setting = get_test_bios_setting(**kw)
    dbapi = db_api.get_instance()
    node_id = bios_setting['node_id']
    version = bios_setting['version']
    settings = [{'name': bios_setting['name'],
                 'value': bios_setting['value'],
                 'attribute_type': bios_setting['attribute_type'],
                 'allowable_values': bios_setting['allowable_values'],
                 'read_only': bios_setting['read_only'],
                 'reset_required': bios_setting['reset_required'],
                 'unique': bios_setting['unique']}]
    return dbapi.create_bios_setting_list(node_id, settings, version)[0]


def get_test_bios_setting(**kw):
    return {
        'node_id': kw.get('node_id', '123'),
        'name': kw.get('name', 'virtualization'),
        'value': kw.get('value', 'on'),
        'attribute_type': kw.get('attribute_type', 'Enumeration'),
        'allowable_values': kw.get('allowable_values', ['on', 'off']),
        'lower_bound': kw.get('lower_bound', None),
        'max_length': kw.get('max_length', None),
        'min_length': kw.get('max_length', None),
        'read_only': kw.get('read_only', False),
        'reset_required': kw.get('reset_required', True),
        'unique': kw.get('unique', False),
        'upper_bound': kw.get('upper_bound', None),
        'version': kw.get('version', bios.BIOSSetting.VERSION),
        'created_at': kw.get('created_at'),
        'updated_at': kw.get('updated_at'),
    }


def get_test_bios_setting_setting_list():
    return [
        {'name': 'virtualization', 'value': 'on'},
        {'name': 'hyperthread', 'value': 'enabled'},
        {'name': 'numlock', 'value': 'off'}
    ]


def get_test_allocation(**kw):
    return {
        'candidate_nodes': kw.get('candidate_nodes', []),
        'conductor_affinity': kw.get('conductor_affinity'),
        'created_at': kw.get('created_at'),
        'extra': kw.get('extra', {}),
        'id': kw.get('id', 42),
        'last_error': kw.get('last_error'),
        'name': kw.get('name'),
        'node_id': kw.get('node_id'),
        'resource_class': kw.get('resource_class', 'baremetal'),
        'state': kw.get('state', 'allocating'),
        'traits': kw.get('traits', []),
        'updated_at': kw.get('updated_at'),
        'uuid': kw.get('uuid', uuidutils.generate_uuid()),
        'version': kw.get('version', allocation.Allocation.VERSION),
        'owner': kw.get('owner', None),
    }


def create_test_allocation(**kw):
    allocation = get_test_allocation(**kw)
    if 'id' not in kw:
        del allocation['id']
    dbapi = db_api.get_instance()
    return dbapi.create_allocation(allocation)


def get_test_deploy_template(**kw):
    default_uuid = uuidutils.generate_uuid()
    return {
        'version': kw.get('version', deploy_template.DeployTemplate.VERSION),
        'created_at': kw.get('created_at'),
        'updated_at': kw.get('updated_at'),
        'id': kw.get('id', 234),
        'name': kw.get('name', u'CUSTOM_DT1'),
        'uuid': kw.get('uuid', default_uuid),
        'steps': kw.get('steps', [get_test_deploy_template_step(
            deploy_template_id=kw.get('id', 234))]),
        'extra': kw.get('extra', {}),
    }


def get_test_deploy_template_step(**kw):
    return {
        'created_at': kw.get('created_at'),
        'updated_at': kw.get('updated_at'),
        'id': kw.get('id', 345),
        'deploy_template_id': kw.get('deploy_template_id', 234),
        'interface': kw.get('interface', 'raid'),
        'step': kw.get('step', 'create_configuration'),
        'args': kw.get('args', {'logical_disks': []}),
        'priority': kw.get('priority', 10),
    }


def create_test_deploy_template(**kw):
    """Create a deployment template in the DB and return DeployTemplate model.

    :param kw: kwargs with overriding values for the deploy template.
    :returns: Test DeployTemplate DB object.
    """
    template = get_test_deploy_template(**kw)
    dbapi = db_api.get_instance()
    # Let DB generate an ID if one isn't specified explicitly.
    if 'id' not in kw:
        del template['id']
    if 'steps' not in kw:
        for step in template['steps']:
            del step['id']
            del step['deploy_template_id']
    else:
        for kw_step, template_step in zip(kw['steps'], template['steps']):
            if 'id' not in kw_step:
                del template_step['id']
    return dbapi.create_deploy_template(template)


def get_test_ibmc_info():
    return {
        "ibmc_address": "https://example.com",
        "ibmc_username": "username",
        "ibmc_password": "password",
        "verify_ca": False,
    }


def get_test_history(**kw):
    return {
        'id': kw.get('id', 345),
        'version': kw.get('version', node_history.NodeHistory.VERSION),
        'uuid': kw.get('uuid', '6f8a5d5c-0f2d-4b2c-a62a-a38e300e3f31'),
        'node_id': kw.get('node_id', 123),
        'event': kw.get('event', 'Something is wrong'),
        'conductor': kw.get('conductor', 'host-1'),
        'severity': kw.get('severity', 'ERROR'),
        'event_type': kw.get('event_type', 'provisioning'),
        'user': kw.get('user', 'fake-user'),
        'created_at': kw.get('created_at'),
        'updated_at': kw.get('updated_at'),
    }


def create_test_history(**kw):
    """Create test history entry in DB and return NodeHistory DB object.

    :param kw: kwargs with overriding values for port's attributes.
    :returns: Test NodeHistory DB object.
    """
    history = get_test_history(**kw)
    # Let DB generate ID if it isn't specified explicitly
    if 'id' not in kw:
        del history['id']
    dbapi = db_api.get_instance()
    return dbapi.create_node_history(history)


def get_test_inventory(**kw):
    return {
        'id': kw.get('id', 345),
        'version': kw.get('version', node_inventory.NodeInventory.VERSION),
        'node_id': kw.get('node_id', 123),
        'inventory_data': kw.get('inventory', {"inventory": "test"}),
        'plugin_data': kw.get('plugin_data', {"pdata": {"plugin": "data"}}),
        'created_at': kw.get('created_at'),
        'updated_at': kw.get('updated_at'),
    }


def create_test_inventory(**kw):
    """Create test inventory entry in DB and return NodeInventory DB object.

    :param kw: kwargs with overriding values for port's attributes.
    :returns: Test NodeInventory DB object.
    """
    inventory = get_test_inventory(**kw)
    # Let DB generate ID if it isn't specified explicitly
    if 'id' not in kw:
        del inventory['id']
    dbapi = db_api.get_instance()
    return dbapi.create_node_inventory(inventory)
