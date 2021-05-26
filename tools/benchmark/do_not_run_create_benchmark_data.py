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

import sys
import time

from oslo_db.sqlalchemy import enginefacade
from sqlalchemy import sql

from ironic.common import service
from ironic.conf import CONF  # noqa To Load Configuration
from ironic.objects import node


def _create_test_nodes():
    print("Starting creation of fake nodes.")
    start = time.time()
    node_count = 10000
    checkin = time.time()
    for i in range(0, node_count):

        new_node = node.Node({
            'power_state': 'power off',
            'driver': 'ipmi',
            'driver_internal_info': {'test-meow': i},
            'name': 'BenchmarkTestNode-%s' % i,
            'driver_info': {
                'ipmi_username': 'admin',
                'ipmi_password': 'admin',
                'ipmi_address': 'testhost%s.env.top.level.domain' % i},
            'resource_class': 'CUSTOM_BAREMETAL',
            'properties': {
                'cpu': 4,
                'memory': 32,
                'cats': i,
                'meowing': True}})
        new_node.create()
        delta = time.time() - checkin
        if delta > 10:
            checkin = time.time()
            print('* At %s nodes, %0.02f seconds. Total elapsed: %s'
                  % (i, delta, time.time() - start))
    created = time.time()
    elapse = created - start
    print('Created %s nodes in %s seconds.\n' % (node_count, elapse))


def _mix_up_nodes_data():
    engine = enginefacade.writer.get_engine()
    conn = engine.connect()

    # A list of commands to mix up indexed field data a bit to emulate what
    # a production database may somewhat look like.
    commands = [
        "UPDATE nodes set maintenance = True where RAND() < 0.1",  # noqa Easier to read this way
        "UPDATE nodes set driver = 'redfish' where RAND() < 0.5",  # noqa Easier to read this way
        "UPDATE nodes set reservation = 'fake_conductor01' where RAND() < 0.02",  # noqa Easier to read this way
        "UPDATE nodes set reservation = 'fake_conductor02' where RAND() < 0.02",  # noqa Easier to read this way
        "UPDATE nodes set reservation = 'fake_conductor03' where RAND() < 0.02",  # noqa Easier to read this way
        "UPDATE nodes set reservation = 'fake_conductor04' where RAND() < 0.02",  # noqa Easier to read this way
        "UPDATE nodes set reservation = 'fake_conductor05' where RAND() < 0.02",  # noqa Easier to read this way
        "UPDATE nodes set reservation = 'fake_conductor06' where RAND() < 0.02",  # noqa Easier to read this way
        "UPDATE nodes set provision_state = 'active' where RAND() < 0.8",  # noqa Easier to read this way
        "UPDATE nodes set power_state = 'power on' where provision_state = 'active' and RAND() < 0.95",  # noqa Easier to read this way
        "UPDATE nodes set provision_state = 'available' where RAND() < 0.1",  # noqa Easier to read this way
        "UPDATE nodes set provision_state = 'manageable' where RAND() < 0.1",  # noqa Easier to read this way
        "UPDATE nodes set provision_state = 'clean wait' where RAND() < 0.05",  # noqa Easier to read this way
        "UPDATE nodes set provision_state = 'error' where RAND() < 0.05",  # noqa Easier to read this way
        "UPDATE nodes set owner = (select UUID()) where RAND() < 0.2",  # noqa Easier to read this way
        "UPDATE nodes set lessee = (select UUID()) where RAND() < 0.2",  # noqa Easier to read this way
        "UPDATE nodes set instance_uuid = (select UUID()) where RAND() < 0.95 and provision_state = 'active'",  # noqa Easier to read this way
        "UPDATE nodes set last_error = (select UUID()) where RAND() <0.05",  # noqa Easier to read this way
    ]
    start = time.time()
    for command in commands:
        print("Executing SQL command: \\" + command + ";\n")
        conn.execute(sql.text(command))
        print("* Completed command. %0.04f elapsed since start of commands."
              % (time.time() - start))


def main():
    service.prepare_service()
    CONF.set_override('debug', False)
    _create_test_nodes()


if __name__ == '__main__':
    sys.exit(main())
