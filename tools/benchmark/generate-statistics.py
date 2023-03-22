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

import datetime
import sys
import time
from unittest import mock

from ironic_lib import metrics_utils
import oslo_policy
from oslo_utils import timeutils

from ironic.api.controllers.v1 import node as node_api
from ironic.api.controllers.v1 import port as port_api
from ironic.api.controllers.v1 import utils as api_utils
from ironic.common import context
from ironic.common import service
from ironic.conf import CONF  # noqa To Load Configuration
from ironic.db import api as db_api
from ironic.objects import conductor
from ironic.objects import node
from ironic.objects import port


def _calculate_delta(start, finish):
    return finish - start


def _add_a_line():
    print('------------------------------------------------------------')


def _assess_db_performance():
    start = time.time()
    dbapi = db_api.get_instance()
    print('Phase - Assess DB performance')
    _add_a_line()
    got_connection = time.time()
    nodes = dbapi.get_node_list()
    node_count = len(nodes)
    query_complete = time.time()
    delta = _calculate_delta(start, got_connection)
    print('Obtained DB client in %s seconds.' % delta)
    delta = _calculate_delta(got_connection, query_complete)
    print('Returned %s nodes in python %s seconds from the DB.\n' %
          (node_count, delta))
    # return node count for future use.
    return node_count


def _assess_db_performance_ports():
    start = time.time()
    dbapi = db_api.get_instance()
    print('Phase - Assess DB performance - Ports')
    _add_a_line()
    got_connection = time.time()
    ports = dbapi.get_port_list()
    port_count = len(ports)
    query_complete = time.time()
    delta = _calculate_delta(start, got_connection)
    print('Obtained DB client in %s seconds.' % delta)
    delta = _calculate_delta(got_connection, query_complete)
    print('Returned %s ports in python %s seconds from the DB.\n' %
          (port_count, delta))
    # return node count for future use.
    return port_count


def _assess_db_and_object_performance():
    print('Phase - Assess DB & Object conversion Performance')
    _add_a_line()
    start = time.time()
    node_list = node.Node().list(context.get_admin_context())
    got_list = time.time()
    delta = _calculate_delta(start, got_list)
    print('Obtained list of node objects in %s seconds.' % delta)
    count = 0
    tbl_size = 0
    # In a sense, this helps provide a relative understanding if the
    # database is the bottleneck, or the objects post conversion.
    # converting completely to json and then measuring the size helps
    # ensure that everything is "assessed" while not revealing too
    # much detail.
    for node_obj in node_list:
        # Just looping through the entire set to count should be
        # enough to ensure that the entry is loaded from the db
        # and then converted to an object.
        tbl_size = tbl_size + sys.getsizeof(node_obj.as_dict(secure=True))
        count = count + 1
    delta = _calculate_delta(got_list, time.time())
    print('Took %s seconds to iterate through %s node objects.' %
          (delta, count))
    print('Nodes table is roughly %s bytes of JSON.\n' % tbl_size)
    observed_vendors = []
    for node_obj in node_list:
        vendor = node_obj.driver_internal_info.get('vendor')
        if vendor:
            observed_vendors.append(vendor)


def _assess_db_and_object_performance_ports():
    print('Phase - Assess DB & Object conversion Performance - Ports')
    _add_a_line()
    start = time.time()
    port_list = port.Port().list(context.get_admin_context())
    got_list = time.time()
    delta = _calculate_delta(start, got_list)
    print('Obtained list of port objects in %s seconds.' % delta)
    count = 0
    tbl_size = 0
    # In a sense, this helps provide a relative understanding if the
    # database is the bottleneck, or the objects post conversion.
    # converting completely to json and then measuring the size helps
    # ensure that everything is "assessed" while not revealing too
    # much detail.
    for port_obj in port_list:
        # Just looping through the entire set to count should be
        # enough to ensure that the entry is loaded from the db
        # and then converted to an object.
        tbl_size = tbl_size + sys.getsizeof(port_obj.as_dict())
        count = count + 1
    delta = _calculate_delta(got_list, time.time())
    print('Took %s seconds to iterate through %s port objects.' %
          (delta, count))
    print('Ports table is roughly %s bytes of JSON.\n' % tbl_size)


@mock.patch('ironic.api.request')  # noqa patch needed for the object model
@mock.patch.object(metrics_utils, 'get_metrics_logger', lambda *_: mock.Mock)
@mock.patch.object(api_utils, 'check_list_policy', lambda *_: None)
@mock.patch.object(api_utils, 'check_allow_specify_fields', lambda *_: None)
@mock.patch.object(api_utils, 'check_allowed_fields', lambda *_: None)
@mock.patch.object(oslo_policy.policy, 'LOG', autospec=True)
def _assess_db_object_and_api_performance(mock_log, mock_request):
    print('Phase - Assess DB & Object conversion Performance')
    _add_a_line()
    # Just mock it to silence it since getting the logger to update
    # config seems like not a thing once started. :\
    mock_log.debug = mock.Mock()
    # Internal logic requires major/minor versions and a context to
    # proceed. This is just to make the NodesController respond properly.
    mock_request.context = context.get_admin_context()
    mock_request.version.major = 1
    mock_request.version.minor = 71

    start = time.time()
    node_api_controller = node_api.NodesController()
    node_api_controller.context = context.get_admin_context()
    fields = ("uuid,power_state,target_power_state,provision_state,"
              "target_provision_state,last_error,maintenance,properties,"
              "instance_uuid,traits,resource_class")

    total_nodes = 0

    res = node_api_controller._get_nodes_collection(
        resource_url='nodes',
        chassis_uuid=None,
        instance_uuid=None,
        associated=None,
        maintenance=None,
        retired=None,
        provision_state=None,
        marker=None,
        limit=None,
        sort_key="id",
        sort_dir="asc",
        fields=fields.split(','))
    total_nodes = len(res['nodes'])
    while len(res['nodes']) != 1:
        print(" ** Getting nodes ** %s Elapsed: %s seconds." %
              (total_nodes, _calculate_delta(start, time.time())))
        res = node_api_controller._get_nodes_collection(
            resource_url='nodes',
            chassis_uuid=None,
            instance_uuid=None,
            associated=None,
            maintenance=None,
            retired=None,
            provision_state=None,
            marker=res['nodes'][-1]['uuid'],
            limit=None,
            sort_key="id",
            sort_dir="asc",
            fields=fields.split(','))
        new_nodes = len(res['nodes'])
        if new_nodes == 0:
            break
        total_nodes = total_nodes + new_nodes

    delta = _calculate_delta(start, time.time())
    print('Took %s seconds to return all %s nodes via '
          'nodes API call pattern.\n' % (delta, total_nodes))



@mock.patch('ironic.api.request')  # noqa patch needed for the object model
@mock.patch.object(metrics_utils, 'get_metrics_logger', lambda *_: mock.Mock)
@mock.patch.object(api_utils, 'check_list_policy', lambda *_: None)
@mock.patch.object(api_utils, 'check_allow_specify_fields', lambda *_: None)
@mock.patch.object(api_utils, 'check_allowed_fields', lambda *_: None)
@mock.patch.object(oslo_policy.policy, 'LOG', autospec=True)
def _assess_db_object_and_api_performance_ports(mock_log, mock_request):
    print('Phase - Assess DB & Object conversion Performance - Ports')
    _add_a_line()
    # Just mock it to silence it since getting the logger to update
    # config seems like not a thing once started. :\
    mock_log.debug = mock.Mock()
    # Internal logic requires major/minor versions and a context to
    # proceed. This is just to make the NodesController respond properly.
    mock_request.context = context.get_admin_context()
    mock_request.version.major = 1
    mock_request.version.minor = 71

    start = time.time()
    port_api_controller = port_api.PortsController()
    port_api_controller.context = context.get_admin_context()
    fields = ("uuid,node_uuid,address,extra,local_link_connection,"
              "pxe_enabled,internal_info,physical_network,"
              "is_smartnic")

    total_ports = 0

    res = port_api_controller._get_ports_collection(
        resource_url='ports',
        node_ident=None,
        address=None,
        portgroup_ident=None,
        shard=None,
        marker=None,
        limit=None,
        sort_key="id",
        sort_dir="asc",
        fields=fields.split(','))
    total_ports = len(res['ports'])
    while len(res['ports']) != 1:
        print(" ** Getting ports ** %s Elapsed: %s seconds." %
              (total_ports, _calculate_delta(start, time.time())))
        res = port_api_controller._get_ports_collection(
            resource_url='ports',
            node_ident=None,
            address=None,
            portgroup_ident=None,
            shard=None,
            marker=res['ports'][-1]['uuid'],
            limit=None,
            sort_key="id",
            sort_dir="asc",
            fields=fields.split(','))
        new_ports = len(res['ports'])
        if new_ports == 0:
            break
        total_ports = total_ports + new_ports

    delta = _calculate_delta(start, time.time())
    print('Took %s seconds to return all %s ports via '
          'ports API call pattern.\n' % (delta, total_ports))


def _report_conductors():
    print('Phase - identifying conductors/drivers')
    _add_a_line()
    conductors = conductor.Conductor().list(
        context.get_admin_context(),
    )
    drivers = []
    groups = []
    online_count = 0
    online_by = timeutils.utcnow(with_timezone=True) - \
        datetime.timedelta(seconds=90)
    for conductor_obj in conductors:
        if conductor_obj.conductor_group:
            groups.append(conductor_obj.conductor_group)
        if conductor_obj.updated_at > online_by:
            online_count = online_count + 1
            for driver in conductor_obj.drivers:
                drivers.append(driver)
    conductor_count = len(conductors)
    print('Conductor count: %s' % conductor_count)
    print('Online conductor count: %s' % online_count)
    running_with_groups = len(groups)
    print('Conductors with conductor_groups: %s' % running_with_groups)
    group_count = len(set(groups))
    print('Conductor group count: %s' % group_count)
    driver_list = list(set(drivers))
    print('Presently supported drivers: %s' % driver_list)


def main():
    service.prepare_command()
    CONF.set_override('debug', False)
    _assess_db_performance()
    _assess_db_and_object_performance()
    _assess_db_object_and_api_performance()
    _assess_db_performance_ports()
    _assess_db_and_object_performance_ports()
    _assess_db_object_and_api_performance_ports()
    _report_conductors()


if __name__ == '__main__':
    sys.exit(main())
