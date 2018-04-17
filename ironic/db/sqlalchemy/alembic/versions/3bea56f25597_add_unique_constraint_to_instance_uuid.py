# Copyright 2014 Red Hat, Inc.
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

"""add unique constraint to instance_uuid

Revision ID: 3bea56f25597
Revises: 31baaf680d2b
Create Date: 2014-06-05 11:45:07.046670

"""

from alembic import op

# revision identifiers, used by Alembic.
revision = '3bea56f25597'
down_revision = '31baaf680d2b'


def upgrade():
    op.create_unique_constraint("uniq_nodes0instance_uuid", "nodes",
                                ["instance_uuid"])
    op.drop_index('node_instance_uuid', 'nodes')
