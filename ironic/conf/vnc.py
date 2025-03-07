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

import os

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
    cfg.BoolOpt(
        'read_only',
        default=False,
        help='When True, keyboard and mouse events will not be passed '
             'to the console.'
    ),
    cfg.IntOpt(
        'token_timeout',
        default=600,
        min=10,
        help='The lifetime of a console auth token (in seconds).'),
    cfg.IntOpt(
        'expire_console_session_interval',
        default=120,
        min=1,
        help='Interval (in seconds) between periodic checks to determine '
             'whether active console sessions have expired and need to be '
             'closed.'),
    cfg.StrOpt(
        'container_provider',
        default='fake',
        help='Console container provider which manages the containers that '
             'expose a VNC service to ironic-novncproxy or nova-novncproxy. '
             'Each container runs an X11 session and a browser showing the '
             'actual BMC console. '
             '"systemd" manages containers as systemd units via podman '
             'Quadlet support. The default is "fake" which returns an '
             'unusable VNC host and port. This needs to be changed if enabled '
             'is True'),
    cfg.StrOpt(
        'console_image',
        mutable=True,
        help='Container image reference for the "systemd" console container '
             'provider, and any other out-of-tree provider which requires a '
             'configurable image reference.'),
    cfg.StrOpt(
        'systemd_container_template',
        default=os.path.join(
            '$pybasedir',
            'console/container/ironic-console.container.template'),
        mutable=True,
        help='For the systemd provider, path to the template for defining a '
             'console container. The default template requires that '
             '"console_image" be set.'),
    cfg.StrOpt(
        'systemd_container_publish_port',
        default='$my_ip::5900',
        help='Equivalent to the podman run --port argument for the '
             'mapping of VNC port 5900 to the host. An IP address is '
             'required to bind to, defaulting to $my_ip. The VNC port '
             'exposed on the host will be a randomly allocated high port. '
             'These containers expose VNC servers which must be accessible '
             'by ironic-novncproxy and/or nova-novncproxy. The VNC servers '
             'have no authentication or encryption so they also should not '
             'be exposed to public access. Additionally, the containers '
             'need to be able to access BMC management endpoints. '),
    cfg.StrOpt(
        'ssl_cert_file',
        help="Certificate file to use when starting the server securely."),
    cfg.StrOpt(
        'ssl_key_file',
        help="Private key file to use when starting the server securely."),
    cfg.StrOpt(
        'ssl_minimum_version',
        help="The minimum SSL version to use."),
    cfg.StrOpt(
        'ssl_ciphers',
        help="Sets the list of available ciphers. value should be a "
             "string in the OpenSSL cipher list format."),
]


def register_opts(conf):
    conf.register_opts(opts, group='vnc')
