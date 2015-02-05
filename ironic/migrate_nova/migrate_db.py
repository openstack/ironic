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
from __future__ import print_function
import argparse
import ConfigParser
import os
import sys

import sqlalchemy as sa
from sqlalchemy.orm import sessionmaker

from ironic.common import states as ironic_states
from ironic.common import utils
from ironic.db.sqlalchemy import models as ironic_models
from ironic.migrate_nova import nova_baremetal_states as nova_states
from ironic.migrate_nova import nova_models


DESCRIPTION = """
This is an administrative utility to be used for migrating a nova-baremetal
node inventory to Ironic.  It will migrate nova-baremetal node and interface
information and associated driver configuration from the Nova database to the
Ironic database. It only supports migrating from the IPMI and
VirtualPowerManager power drivers.
"""

IRONIC_ENGINE = None
NOVA_BM_ENGINE = None


# Relevant nova-baremetal config with their associated defaults as of Juno.
NOVA_BM_CONFIG_KEYS = {
    # nova.virt.baremetal.driver
    'driver': 'nova.virt.baremetal.pxe.PXE',
    'power_manager': 'nova.virt.baremetal.ipmi.IPMI',

    # nova.virt.baremetal.virtual_power_driver
    'virtual_power_ssh_host': '',
    'virtual_power_ssh_port': 22,
    'virtual_power_type': 'virsh',
    'virtual_power_host_user': '',
    'virtual_power_host_pass': '',
    'virtual_power_host_key': '',
}


def get_nova_nodes():
    Session = sessionmaker(bind=NOVA_BM_ENGINE)
    session = Session()
    query = session.query(nova_models.BareMetalNode)

    try:
        nodes = query.all()
    except sa.exc.OperationalError as err:
        print("Could not get nodes from Nova:\n%s" % err, file=sys.stderr)
        sys.exit(2)

    session.close()

    return nodes


def get_nova_ports():
    Session = sessionmaker(bind=NOVA_BM_ENGINE)
    session = Session()

    query = session.query(nova_models.BareMetalInterface)

    try:
        ports = query.all()
    except sa.exc.OperationalError as err:
        print("Could not get ports from Nova:\n%s" % err, file=sys.stderr)
        sys.exit(2)

    session.close()

    return ports


def convert_nova_nodes(nodes, cpu_arch, nova_conf):
    ironic_nodes = []

    for n_node in nodes:
        # Create an empty Ironic Node
        i_node = ironic_models.Node()

        # Populate basic properties
        i_node.id = n_node.id
        i_node.uuid = n_node.uuid
        i_node.chassis_id = None
        i_node.last_error = None
        i_node.instance_uuid = n_node.instance_uuid
        i_node.reservation = None
        i_node.maintenance = False
        i_node.updated_at = n_node.updated_at
        i_node.created_at = n_node.created_at

        # Populate states
        if n_node.task_state == nova_states.ACTIVE:
            i_node.power_state = ironic_states.POWER_ON
        else:
            i_node.power_state = ironic_states.POWER_OFF

        i_node.target_power_state = None

        if i_node.instance_uuid:
            prov_state = ironic_states.ACTIVE
        else:
            prov_state = ironic_states.NOSTATE

        i_node.provision_state = prov_state
        i_node.target_provision_state = None

        # Populate extra properties
        i_node.extra = {}

        # Populate driver_info
        i_node.driver_info = {}

        power_manager = nova_conf['power_manager']
        if power_manager.endswith('IPMI'):
            i_node.driver = 'pxe_ipmitool'
            if n_node.pm_address:
                i_node.driver_info['ipmi_address'] = n_node.pm_address
            if n_node.pm_user:
                i_node.driver_info['ipmi_username'] = n_node.pm_user
            if n_node.pm_password:
                i_node.driver_info['ipmi_password'] = n_node.pm_password
        elif power_manager.endswith('VirtualPowerManager'):
            i_node.driver = 'pxe_ssh'
            i_node.driver_info = {
                'ssh_virt_type': nova_conf['virtual_power_type'],
                'ssh_address': nova_conf['virtual_power_ssh_host'],
                'ssh_username': nova_conf['virtual_power_host_user'],
            }

            ssh_port = nova_conf.get('ssh_port')
            if ssh_port:
                ssh_port = nova_conf['virtual_power_ssh_port']

            ssh_key = nova_conf.get('virtual_power_host_key')
            if ssh_key:
                i_node.driver_info['ssh_key_filename'] = ssh_key

            ssh_pass = nova_conf.get('virtual_power_host_pass')
            if ssh_pass:
                i_node.driver_info['ssh_password'] = ssh_pass
        else:
            print("This does not support migration from power driver: "
                  "%s\n" % nova_conf['driver'], file=sys.stderr)
            sys.exit(2)

        # Populate instance_info
        i_node.instance_info = {}

        if n_node.root_mb:
            i_node.instance_info['root_mb'] = n_node.root_mb
        if n_node.swap_mb:
            i_node.instance_info['swap_mb'] = n_node.swap_mb
        if n_node.ephemeral_mb:
            i_node.instance_info['ephemeral_mb'] = n_node.ephemeral_mb

        i_node.properties = {'cpu_arch': cpu_arch,
                             'cpus': n_node.cpus,
                             'local_gb': n_node.local_gb,
                             'memory_mb': n_node.memory_mb}

        ironic_nodes.append(i_node)

    return ironic_nodes


def convert_nova_ports(ports):
    ironic_ports = []

    for n_port in ports:
        i_port = ironic_models.Port()

        i_port.id = n_port.id
        i_port.uuid = utils.generate_uuid()
        i_port.address = n_port.address
        i_port.node_id = n_port.bm_node_id

        i_port.extra = {}

        if n_port.vif_uuid:
            i_port.extra['vif_uuid'] = n_port.vif_uuid

        ironic_ports.append(i_port)

    return ironic_ports


def save_ironic_objects(objects):
    Session = sessionmaker(bind=IRONIC_ENGINE)
    session = Session()

    try:
        session.add_all(objects)
        session.commit()
    except sa.exc.OperationalError as err:
        print("Could not send data to Ironic:\n%s" % err, file=sys.stderr)
        sys.exit(2)

    session.close()


def parse_nova_config(config_file):
    """Parse nova.conf and return known defaults if setting is not present.

    This avoids having to import nova code from this script and risk conflicts
    with Ironic's tree around oslo_config resources.
    """
    if not os.path.isfile(config_file):
        print("nova.conf not found at %s. Please specify the location via "
              "the --nova-config option." % config_file, file=sys.stderr)
        sys.exit(1)
    nova_conf = ConfigParser.SafeConfigParser()
    nova_conf.read(config_file)

    conf = {}
    for setting, default in NOVA_BM_CONFIG_KEYS.items():
        try:
            conf[setting] = nova_conf.get('baremetal', setting)
        except ConfigParser.NoOptionError:
            conf[setting] = default
    return conf


def validate_config(config):
    """Early validation of required configuration prior to touching the db."""
    if config['power_manager'].endswith('VirtualPowerManager'):
        # confirm nova.conf contains all required ssh info, as per
        # ironic.drivers.ssh.REQUIRED_PROPERTIES.
        req = ['virtual_power_host_user', 'virtual_power_type',
               'virtual_power_ssh_host']
        missing = []
        for r in req:
            if not config.get(r):
                missing.append(r)
        if missing:
            print('nova.conf is missing required settings in the '
                  '[baremetal] section to migrate VirtualPowerManager: %s' %
                  ' '.join(missing), file=sys.stderr)
            sys.exit(1)


def parse_args():
    parser = argparse.ArgumentParser(description=DESCRIPTION)
    parser.add_argument('--nova-bm-db', '-b', type=str,
                        required=True, dest='nova_bm_conn_string',
                        help='Connection string to Nova baremetal database.')
    parser.add_argument('--ironic-db', '-i', type=str,
                        required=True, dest='ironic_conn_string',
                        help='Connection string to Ironic database.')
    parser.add_argument('--node-arch', '-a', type=str,
                        required=True, dest='cpu_arch',
                        help='CPU architecture of the nodes.')
    parser.add_argument('--nova-config', '-c', type=str,
                        required=False, dest='nova_config',
                        default='/etc/nova/nova.conf',
                        help='Path to nova.conf. (default: '
                             '/etc/nova/nova.conf)')
    return parser.parse_args(sys.argv[1:])


def main():
    args = parse_args()

    global IRONIC_ENGINE
    global NOVA_BM_ENGINE

    IRONIC_ENGINE = sa.create_engine(args.ironic_conn_string)
    NOVA_BM_ENGINE = sa.create_engine(args.nova_bm_conn_string)

    # Load and validate nova.conf
    nova_conf = parse_nova_config(args.nova_config)
    validate_config(nova_conf)

    # Process nodes
    print("Getting data for baremetal nodes from Nova...")
    nova_nodes = get_nova_nodes()
    print("Got %d nodes from Nova..." % len(nova_nodes))

    print("Converting information for Nova nodes to Ironic...")
    ironic_nodes = convert_nova_nodes(nova_nodes, args.cpu_arch,
                                      nova_conf)

    print("Saving nodes to Ironic...")
    save_ironic_objects(ironic_nodes)

    # Process ports
    print("Getting baremetal ports from Nova...")
    nova_ports = get_nova_ports()
    print("Got %d ports from Nova." % len(nova_ports))

    print("Converting Nova ports...")
    ironic_ports = convert_nova_ports(nova_ports)
    print("Saving ports to Ironic...")
    save_ironic_objects(ironic_ports)

    # Printing summary
    print("All done!")
    print("%d nodes and %d ports have been migrated from "
          "Nova to Ironic." % (len(nova_nodes), len(nova_ports)))


if __name__ == '__main__':
    main()
