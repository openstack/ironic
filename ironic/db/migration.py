# Copyright 2010 United States Government as represented by the
# Administrator of the National Aeronautics and Space Administration.
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

"""Database setup and migration commands."""

from oslo_config import cfg
from stevedore import driver

_IMPL = None


def get_backend():
    global _IMPL
    if not _IMPL:
        cfg.CONF.import_opt('backend', 'oslo_db.options', group='database')
        _IMPL = driver.DriverManager("ironic.database.migration_backend",
                                     cfg.CONF.database.backend).driver
    return _IMPL


def upgrade(version=None):
    """Migrate the database to `version` or the most recent version."""
    return get_backend().upgrade(version)


def version():
    return get_backend().version()


def stamp(version):
    return get_backend().stamp(version)


def revision(message, autogenerate):
    return get_backend().revision(message, autogenerate)


def create_schema():
    return get_backend().create_schema()
