#   Copyright 2025 Red Hat, Inc.
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


opts = [
    cfg.StrOpt(
        'public_url',
        mutable=True,
        help='Public URL to use when building the links to the noVNC client '
             'browser page '
             '(for example, "http://127.0.0.1:6090/vnc_auto.html"). '
             'If the API is operating behind a proxy, you '
             'will want to change this to represent the proxy\'s URL. '
             'Defaults to None. '),
    cfg.IntOpt(
        'token_timeout',
        default=600,
        min=10,
        help='The lifetime of a console auth token (in seconds).'),
]


def register_opts(conf):
    conf.register_opts(opts, group='vnc')
