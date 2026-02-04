# Copyright (c) 2018 NEC, Corp.
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

from oslo_config import cfg
from oslo_db.sqlalchemy import enginefacade
from oslo_db.sqlalchemy import utils
from oslo_upgradecheck import common_checks
from oslo_upgradecheck import upgradecheck
import sqlalchemy

from ironic.command import dbsync
from ironic.common import driver_factory
from ironic.common.i18n import _
from ironic.common import policy  # noqa importing to load policy config.
import ironic.conf
from ironic.db import api as db_api

CONF = ironic.conf.CONF


class Checks(upgradecheck.UpgradeCommands):

    """Upgrade checks for the ironic-status upgrade check command

    Upgrade checks should be added as separate methods in this class
    and added to _upgrade_checks tuple.
    """

    def _check_obj_versions(self):
        """Check that the DB versions of objects are compatible.

        Checks that the object versions are compatible with this
        release of ironic. It does this by comparing the objects'
        .version field in the database, with the expected versions
        of these objects.
        """
        try:
            # NOTE(TheJulia): Seems an exception is raised by sqlalchemy
            # when a table is missing, so lets catch it, since it is fatal.
            msg = dbsync.DBCommand().check_obj_versions(
                ignore_missing_tables=True)
        except sqlalchemy.exc.NoSuchTableError as e:
            msg = ('Database table missing. Please ensure you have '
                   'updated the database schema. Not Found: %s' % e)
            return upgradecheck.Result(upgradecheck.Code.FAILURE, details=msg)

        if not msg:
            return upgradecheck.Result(upgradecheck.Code.SUCCESS)
        else:
            return upgradecheck.Result(upgradecheck.Code.FAILURE, details=msg)

    def _check_db_indexes(self):
        """Check if indexes exist on heavily used columns.

        Checks the database to see if indexes exist on heavily used columns
        and provide guidance of action that can be taken to improve ironic
        database performance.
        """
        engine = enginefacade.reader.get_engine()

        indexes = [
            ('nodes', 'reservation_idx'),
            ('nodes', 'driver_idx'),
            ('nodes', 'provision_state_idx'),
            ('nodes', 'conductor_group_idx'),
            ('nodes', 'resource_class_idx'),
            ('nodes', 'reservation_idx'),
            ('nodes', 'owner_idx'),
            ('nodes', 'lessee_idx'),
        ]
        missing_indexes = []
        for table, idx in indexes:
            if not utils.index_exists(engine, table, idx):
                missing_indexes.append(idx)

        if missing_indexes:
            idx_list = ', '.join(missing_indexes)
            msg = ('Indexes missing for ideal database performance. Please '
                   'consult https://docs.openstack.org/ironic/latest/admin/'
                   'tuning.html for information on indexes. Missing: %s'
                   % idx_list)
            return upgradecheck.Result(upgradecheck.Code.WARNING, details=msg)
        else:
            return upgradecheck.Result(upgradecheck.Code.SUCCESS)

    def _check_allocations_table(self):
        msg = None
        engine = enginefacade.reader.get_engine()
        if 'mysql' != str(engine.url.get_backend_name()):
            # This test only applies to mysql and database schema
            # selection.
            return upgradecheck.Result(upgradecheck.Code.SUCCESS)
        with engine.connect() as conn, conn.begin():
            res = conn.execute(
                sqlalchemy.text("show create table allocations"))
        results = str(res.all()).lower()
        # Check for utf8mb4 (4-byte UTF-8) which is the required encoding.
        # Note: 'utf8mb4' will not match 'utf8mb3' or legacy 'utf8' aliases.
        if 'utf8mb4' not in results:
            msg = ('The Allocations table is not using UTF8MB4 encoding. '
                   'Ironic requires UTF8MB4 (4-byte UTF-8) character '
                   'encoding for full Unicode support. Please run '
                   '"ironic-dbsync upgrade" to migrate to UTF8MB4. '
                   'This requires MySQL 8.0+ or MariaDB 10.3+.')

        if 'innodb' not in results:
            warning = ('The engine used by MySQL for the allocations '
                       'table is not the intended engine for the Ironic '
                       'database tables to use. This may have been a result '
                       'of an error with the table creation schema. This '
                       'may require Database Administrator intervention '
                       'and downtime to dump, modify the table engine to '
                       'utilize InnoDB, and reload the allocations table to '
                       'utilize the InnoDB engine.')
            if msg:
                msg = msg + ' Additionally: ' + warning
            else:
                msg = warning

        if msg:
            return upgradecheck.Result(upgradecheck.Code.WARNING, details=msg)
        else:
            return upgradecheck.Result(upgradecheck.Code.SUCCESS)

    def _check_hardware_types_interfaces(self):
        try:
            hw_types = driver_factory.hardware_types()
        except Exception as exc:
            # NOTE(dtantsur): if the hardware types failed to load, we cannot
            # validate the hardware interfaces, so returning early.
            msg = f"Some hardware types cannot be loaded: {exc}"
            return upgradecheck.Result(upgradecheck.Code.FAILURE, details=msg)

        try:
            ifaces = driver_factory.all_interfaces()
        except Exception as exc:
            msg = f"Some hardware interfaces cannot be loaded: {exc}"
            return upgradecheck.Result(upgradecheck.Code.FAILURE, details=msg)

        warnings = []
        for name, obj in hw_types.items():
            if not obj.supported:
                warnings.append(f"Hardware type {name} is deprecated or not "
                                "supported")

        for iface_type, iface_dict in ifaces.items():
            iface_type = iface_type.capitalize()
            for name, obj in iface_dict.items():
                if not obj.supported:
                    warnings.append(f"{iface_type} interface {name} is "
                                    "deprecated or not supported")

        dbapi = db_api.get_instance()
        for node in dbapi.get_node_list():
            if node.driver not in hw_types:
                warnings.append(f"Node {node.uuid} uses an unknown driver "
                                f"{node.driver}")
            for iface_type, iface_dict in ifaces.items():
                value = getattr(node, f"{iface_type}_interface")
                # NOTE(dtantsur): the interface value can be empty if a new
                # interface type has just been added, and nodes have not been
                # updated yet.
                if value and value not in iface_dict:
                    warnings.append(f"Node {node.uuid} uses an unknown "
                                    f"{iface_type} interface {value}")

        if warnings:
            msg = ". ".join(warnings)
            return upgradecheck.Result(upgradecheck.Code.WARNING, details=msg)
        else:
            return upgradecheck.Result(upgradecheck.Code.SUCCESS)

    def _check_ilo_driver_usage(self):
        """Check for nodes using iLO/iLO5 hardware types or interfaces.

        The iLO driver is retired.
        """
        dbapi = db_api.get_instance()

        ilo_interface_types = [
            'bios', 'boot', 'console', 'inspect',
            'management', 'power', 'raid', 'vendor'
        ]

        affected_nodes = []
        for node in dbapi.get_node_list():
            issues = []

            node_driver = node.driver
            if node_driver and node_driver.lower() in ['ilo', 'ilo5']:
                issues.append(f"hardware type '{node_driver}'")

            for iface_type in ilo_interface_types:
                value = getattr(node, f"{iface_type}_interface")
                if value and 'ilo' in value.lower():
                    issues.append(f"{iface_type} interface '{value}'")

            if issues:
                affected_nodes.append(
                    f"Node {node.uuid} uses {', '.join(issues)}")

        if not affected_nodes:
            return upgradecheck.Result(upgradecheck.Code.SUCCESS)

        msg = (
            "The following nodes are using iLO/iLO5 hardware types and/or "
            "interfaces which have been retired as of the 2026.1 release."
            + ". ".join(affected_nodes)
        )
        return upgradecheck.Result(upgradecheck.Code.WARNING, details=msg)

    # A tuple of check tuples of (<name of check>, <check function>).
    # The name of the check will be used in the output of this command.
    # The check function takes no arguments and returns an
    # oslo_upgradecheck.upgradecheck.Result object with the appropriate
    # oslo_upgradecheck.upgradecheck.Code and details set. If the
    # check function hits warnings or failures then those should be stored
    # in the returned Result's "details" attribute. The
    # summary will be rolled up at the end of the check() method.
    _upgrade_checks = (
        (_('Object versions'), _check_obj_versions),
        (_('Database Index Status'), _check_db_indexes),
        (_('MySQL UTF8MB4 Encoding Check'),
         _check_allocations_table),
        # Victoria -> Wallaby migration
        (_('Policy File JSON to YAML Migration'),
         (common_checks.check_policy_json, {'conf': CONF})),
        (_('Hardware Types and Interfaces Check'),
         _check_hardware_types_interfaces),
        (_('iLO/iLO5 Driver Usage Check'),
         _check_ilo_driver_usage),
    )


def main():
    return upgradecheck.main(
        cfg.CONF, project='ironic', upgrade_command=Checks())


if __name__ == '__main__':
    sys.exit(main())
