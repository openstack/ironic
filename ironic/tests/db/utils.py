"""Ironic test utilities."""

from ironic import test
from ironic.openstack.common import jsonutils as json
from ironic.db.sqlalchemy import models


def get_test_node(**kw):
    power_info = json.dumps({'driver': 'ipmi',
                             'user': 'fake-user', 
                             'password': 'fake-password',
                             'address': 'fake-address'})
    node = models.Node()
    node.id = kw.get('id', 123)
    node.uuid = kw.get('uuid', '1be26c0b-03f2-4d2e-ae87-c02d7f33c123')
    node.cpu_arch = kw.get('cpu_arch', 'x86_64')
    node.cpu_num = kw.get('cpu_num', 4)
    node.local_storage_max = kw.get('local_storage_max', 1000)
    node.task_state = kw.get('task_state', 'NOSTATE')
    node.image_path = kw.get('image_path', '/fake/image/path')
    node.instance_uuid = kw.get('instance_uuid',
                                '8227348d-5f1d-4488-aad1-7c92b2d42504')
    node.instance_name = kw.get('instance_name', 'fake-image-name')
    node.power_info = kw.get('power_info', power_info)
    node.extra = kw.get('extra', '{}')

    return node

def get_test_iface(**kw):
    iface = models.Iface()
    iface.id = kw.get('id', 987)
    iface.node_id = kw.get('node_id', 123)
    iface.address = kw.get('address', '52:54:00:cf:2d:31')

    return iface
