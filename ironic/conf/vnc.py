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
from oslo_config import types


opts = [
    cfg.BoolOpt(
        'enabled',
        default=False,
        help='Enable VNC related features. '
             'Guests will get created with graphical devices to support '
             'this. Clients (for example Horizon) can then establish a '
             'VNC connection to the guest.'),
    cfg.HostAddressOpt(
        'host_ip',
        default='0.0.0.0',
        help='The IP address or hostname on which ironic-novncproxy '
             'listens.'),
    cfg.PortOpt(
        'port',
        default=6090,
        help='The TCP port on which ironic-novncproxy listens.'),
    cfg.StrOpt(
        'public_url',
        mutable=True,
        help='Public URL to use when building the links to the noVNC client '
             'browser page '
             '(for example, "http://127.0.0.1:6090/vnc_auto.html"). '
             'If the API is operating behind a proxy, you '
             'will want to change this to represent the proxy\'s URL. '
             'Defaults to None. '),
    cfg.BoolOpt(
        'enable_ssl',
        default=False,
        help='Enable the integrated stand-alone noVNC to service '
             'requests via HTTPS instead of HTTP. If there is a '
             'front-end service performing HTTPS offloading from '
             'the service, this option should be False; note, you '
             'will want to configure [vnc]public_endpoint option '
             'to set URLs in responses to the SSL terminated one.'),
    cfg.StrOpt(
        'novnc_web',
        default='/usr/share/novnc',
        help='Path to directory with content which will be served by a web '
             'server.'),
    cfg.StrOpt(
        'novnc_record',
        help='Filename that will be used for storing websocket frames '
             'received and sent by a VNC proxy service running on this host. '
             'If this is not set, no recording will be done.'),
    cfg.ListOpt(
        'novnc_auth_schemes',
        item_type=types.String(choices=(
            ('none', 'Allow connection without authentication'),
        )),
        default=['none'],
        help='The allowed authentication schemes to use with proxied '
             'VNC connections'),
    cfg.IntOpt(
        'token_timeout',
        default=600,
        min=10,
        help='The lifetime of a console auth token (in seconds).'),
]


def register_opts(conf):
    conf.register_opts(opts, group='vnc')
