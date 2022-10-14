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

from ironic.cmd import dbsync
from ironic.common.i18n import _
from ironic.common import policy  # noqa importing to load policy config.
import ironic.conf

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
        if 'mysql' not in str(engine.url):
            # This test only applies to mysql and database schema
            # selection.
            return upgradecheck.Result(upgradecheck.Code.SUCCESS)
        res = engine.execute("show create table allocations")
        results = str(res.all()).lower()
        if 'utf8' not in results:
            msg = ('The Allocations table is is not using UTF8 encoding. '
                   'This is corrected in later versions of Ironic, where '
                   'the table character set schema is automatically '
                   'migrated. Continued use of a non-UTF8 character '
                   'set may produce unexpected results.')

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
        (_('Allocations Name Field Length Check'),
         _check_allocations_table),
        # Victoria -> Wallaby migration
        (_('Policy File JSON to YAML Migration'),
         (common_checks.check_policy_json, {'conf': CONF})),
    )


def main():
    return upgradecheck.main(
        cfg.CONF, project='ironic', upgrade_command=Checks())


if __name__ == '__main__':
    sys.exit(main())
