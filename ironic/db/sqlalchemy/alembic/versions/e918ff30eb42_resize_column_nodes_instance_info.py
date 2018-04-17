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

"""resize column nodes instance_info

Revision ID: e918ff30eb42
Revises: b4130a7fc904
Create Date: 2016-06-28 13:30:19.396203

"""

from alembic import op
from oslo_db.sqlalchemy import types as db_types

# revision identifiers, used by Alembic.
revision = 'e918ff30eb42'
down_revision = 'b4130a7fc904'


def upgrade():
    op.alter_column('nodes', 'instance_info',
                    existing_type=db_types.JsonEncodedDict.impl,
                    type_=db_types.JsonEncodedDict(mysql_as_long=True).impl)
