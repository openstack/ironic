# vim: tabstop=4 shiftwidth=4 softtabstop=4
# -*- encoding: utf-8 -*-
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

from migrate.changeset import UniqueConstraint
from sqlalchemy import MetaData, Table


def upgrade(migrate_engine):
    meta = MetaData(bind=migrate_engine)
    t = Table('chassis', meta, autoload=True)

    # NOTE: new name convention for UC
    uc = UniqueConstraint('uuid', table=t, name='uniq_chassis0uuid')
    uc.create()


def downgrade(migrate_engine):
    raise NotImplementedError('Downgrade from version 011 is unsupported.')
