# Copyright 2016 Intel Corporation
# Copyright 2014 OpenStack Foundation
# All Rights Reserved
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

opts = [
    cfg.IntOpt('swift_max_retries',
               default=2,
               help=_('Maximum number of times to retry a Swift request, '
                      'before failing.')),
    cfg.BoolOpt('swift_set_temp_url_key',
                default=False,
                help=_('Should the service try to set the temp-url key if missing '))
]


def register_opts(conf):
    conf.register_opts(opts, group='swift')
    auth.register_auth_opts(conf, 'swift', service_type='object-store')


def list_opts():
    return auth.add_auth_opts(opts, service_type='object-store')
