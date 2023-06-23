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


"""remove_extra_fk_constraint in allocations

Revision ID: d163df1bab88
Revises: 163040c5513f
Create Date: 2023-06-23 11:20:10.904262

"""


from alembic import op
from oslo_db import exception as db_exc
from oslo_db.sqlalchemy import enginefacade


# revision identifiers, used by Alembic.
revision = 'd163df1bab88'
down_revision = '163040c5513f'


def upgrade():
    engine = enginefacade.reader.get_engine()

    if engine.dialect.name == 'mysql':
        # Remove the outer level conductor_affinity constraint which pointed
        # to the conductor.id field, when the allocation's table also already
        # points to unique node constraints where a node also has a conductor
        # affinity field on the conductor.id. Removing because this is
        # expected to be come a hard error for SQLAlchemy at some point.
        try:
            op.drop_constraint('allocations_ibfk_1', 'allocations',
                               type_="foreignkey")
            op.drop_constraint('allocations_ibfk_2', 'allocations',
                               type_="foreignkey")
        except db_exc.DBNonExistentConstraint:
            # This is to ignore this issue on newer deployments where
            # key mappings may not already exist.
            pass
