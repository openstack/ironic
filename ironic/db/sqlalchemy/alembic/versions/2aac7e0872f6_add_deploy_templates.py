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

"""Create deploy_templates and deploy_template_steps tables.

Revision ID: 2aac7e0872f6
Revises: 28c44432c9c3
Create Date: 2018-12-27 11:49:15.029650

"""

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = '2aac7e0872f6'
down_revision = '28c44432c9c3'


def upgrade():
    op.create_table(
        'deploy_templates',
        sa.Column('version', sa.String(length=15), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.Column('updated_at', sa.DateTime(), nullable=True),
        sa.Column('id', sa.Integer(), nullable=False,
                  autoincrement=True),
        sa.Column('uuid', sa.String(length=36)),
        sa.Column('name', sa.String(length=255), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('uuid', name='uniq_deploytemplates0uuid'),
        sa.UniqueConstraint('name', name='uniq_deploytemplates0name'),
        mysql_engine='InnoDB',
        mysql_charset='UTF8MB3'
    )

    op.create_table(
        'deploy_template_steps',
        sa.Column('version', sa.String(length=15), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.Column('updated_at', sa.DateTime(), nullable=True),
        sa.Column('id', sa.Integer(), nullable=False,
                  autoincrement=True),
        sa.Column('deploy_template_id', sa.Integer(), nullable=False,
                  autoincrement=False),
        sa.Column('interface', sa.String(length=255), nullable=False),
        sa.Column('step', sa.String(length=255), nullable=False),
        sa.Column('args', sa.Text, nullable=False),
        sa.Column('priority', sa.Integer, nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.ForeignKeyConstraint(['deploy_template_id'],
                                ['deploy_templates.id']),
        sa.Index('deploy_template_id', 'deploy_template_id'),
        sa.Index('deploy_template_steps_interface_idx', 'interface'),
        sa.Index('deploy_template_steps_step_idx', 'step'),
        mysql_engine='InnoDB',
        mysql_charset='UTF8MB3'
    )
