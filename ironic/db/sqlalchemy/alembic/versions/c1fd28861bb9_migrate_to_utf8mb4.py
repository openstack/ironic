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

"""Migrate to UTF8MB4 character encoding

Revision ID: c1fd28861bb9
Revises: 9c0446cb6bc3
Create Date: 2026-01-23 10:00:00.000000

"""

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = 'c1fd28861bb9'
down_revision = '9c0446cb6bc3'


# List of all tables that need to be converted to UTF8MB4
TABLES = [
    'chassis',
    'conductors',
    'conductor_hardware_interfaces',
    'nodes',
    'ports',
    'portgroups',
    'node_tags',
    'volume_connectors',
    'volume_targets',
    'node_traits',
    'bios_settings',
    'allocations',
    'deploy_templates',
    'deploy_template_steps',
    'node_history',
    'node_inventory',
    'firmware_information',
    'runbooks',
    'runbook_steps',
    'inspection_rules',
]

# When MySQL converts tables to UTF8MB4 using CONVERT TO CHARACTER SET,
# it automatically promotes TEXT columns to MEDIUMTEXT to preserve the same
# character capacity (since UTF8MB4 uses 4 bytes per character vs 3 for
# UTF8MB3). We need to explicitly restore these columns to TEXT type.
# This includes both plain Text columns and oslo.db's JsonEncodedDict/List
# types which are stored as TEXT in MySQL.
# Note: Columns with mysql_as_long=True (LONGTEXT) are not affected.
# Format: {table_name: [(column_name, nullable), ...]}
TEXT_COLUMNS = {
    'allocations': [
        ('last_error', True),
        ('traits', True),
        ('candidate_nodes', True),
        ('extra', True),
    ],
    'bios_settings': [
        ('value', True),
        ('allowable_values', True),
    ],
    'chassis': [
        ('extra', True),
    ],
    'conductors': [
        ('drivers', True),
    ],
    'deploy_template_steps': [
        ('args', False),
    ],
    'deploy_templates': [
        ('extra', True),
    ],
    'node_history': [
        ('event', True),
    ],
    'nodes': [
        ('last_error', True),
        ('maintenance_reason', True),
        ('protected_reason', True),
        ('description', True),
        ('retired_reason', True),
        ('properties', True),
        ('driver_info', True),
        ('driver_internal_info', True),
        ('clean_step', True),
        ('deploy_step', True),
        ('raid_config', True),
        ('target_raid_config', True),
        ('extra', True),
        ('network_data', True),
        ('service_step', True),
    ],
    'portgroups': [
        ('extra', True),
        ('internal_info', True),
        ('properties', True),
    ],
    'ports': [
        ('extra', True),
        ('local_link_connection', True),
        ('internal_info', True),
    ],
    'runbook_steps': [
        ('args', False),
    ],
    'runbooks': [
        ('extra', True),
    ],
    'volume_connectors': [
        ('extra', True),
    ],
    'volume_targets': [
        ('properties', True),
        ('extra', True),
    ],
}


def _verify_utf8mb4_conversion(connection):
    """Verify all tables have been converted to utf8mb4.

    Queries information_schema to check that all Ironic tables are using
    utf8mb4 character set. Raises an exception if any table is not converted.
    """
    # Get the database name from the connection
    db_name = connection.execute(
        sa.text("SELECT DATABASE()")
    ).scalar()

    # Check table character sets
    result = connection.execute(sa.text(
        "SELECT TABLE_NAME, TABLE_COLLATION "
        "FROM information_schema.TABLES "
        "WHERE TABLE_SCHEMA = :db_name "
        "AND TABLE_NAME IN :tables "
        "AND (TABLE_COLLATION IS NULL OR TABLE_COLLATION NOT LIKE 'utf8mb4%')"
    ), {"db_name": db_name, "tables": tuple(TABLES)})

    failed_tables = result.fetchall()
    if failed_tables:
        table_list = ", ".join(f"{t[0]} ({t[1]})" for t in failed_tables)
        raise Exception(
            f"UTF8MB4 migration verification failed. "
            f"Tables not using utf8mb4: {table_list}"
        )


def upgrade():
    # This migration only applies to MySQL/MariaDB databases.
    # For other databases (SQLite, PostgreSQL), this is a no-op.
    connection = op.get_bind()
    if connection.dialect.name != 'mysql':
        return

    # Convert each table to UTF8MB4 character set with unicode collation.
    # This requires MySQL 8.0+ or MariaDB 10.3+ which use DYNAMIC row format
    # by default, allowing index key prefixes up to 3072 bytes.
    for table in TABLES:
        op.execute(
            sa.text(
                f"ALTER TABLE {table} CONVERT TO CHARACTER SET utf8mb4 "
                "COLLATE utf8mb4_unicode_ci"
            )
        )

    # Restore TEXT columns that were promoted to MEDIUMTEXT during conversion.
    # This is necessary to keep the schema in sync with the SQLAlchemy models.
    # We batch all column modifications per table into a single ALTER TABLE
    # statement for efficiency (one table rebuild instead of many).
    for table, columns in TEXT_COLUMNS.items():
        modifications = []
        for column, nullable in columns:
            null_str = "NULL" if nullable else "NOT NULL"
            modifications.append(
                f"MODIFY COLUMN {column} TEXT "
                f"CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci {null_str}"
            )
        op.execute(sa.text(
            f"ALTER TABLE {table} " + ", ".join(modifications)
        ))

    # Verify the conversion was successful
    _verify_utf8mb4_conversion(connection)
