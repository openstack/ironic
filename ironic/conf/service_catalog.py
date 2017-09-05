# Copyright 2016 Mirantis Inc
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

from oslo_config import cfg

from ironic.common.i18n import _
from ironic.conf import auth

SERVICE_CATALOG_GROUP = cfg.OptGroup(
    'service_catalog',
    title='Access info for Ironic service user',
    help=_('Holds credentials and session options to access '
           'Keystone catalog for Ironic API endpoint resolution.'))


def register_opts(conf):
    auth.register_auth_opts(conf, SERVICE_CATALOG_GROUP.name,
                            service_type='baremetal')


def list_opts():
    return auth.add_auth_opts([], service_type='baremetal')
