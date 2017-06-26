# Copyright 2016 Intel Corporation
# Copyright 2010 OpenStack Foundation
# Copyright 2013 Hewlett-Packard Development Company, L.P.
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

opts = [
    cfg.ListOpt('allowed_direct_url_schemes',
                default=[],
                help=_('A list of URL schemes that can be downloaded directly '
                       'via the direct_url.  Currently supported schemes: '
                       '[file].')),
    # To upload this key to Swift:
    # swift post -m Temp-Url-Key:secretkey
    # When using radosgw, temp url key could be uploaded via the above swift
    # command, or with:
    # radosgw-admin user modify --uid=user --temp-url-key=secretkey
    cfg.StrOpt('swift_temp_url_key',
               help=_('The secret token given to Swift to allow temporary URL '
                      'downloads. Required for temporary URLs.'),
               secret=True),
    cfg.IntOpt('swift_temp_url_duration',
               default=1200,
               help=_('The length of time in seconds that the temporary URL '
                      'will be valid for. Defaults to 20 minutes. If some '
                      'deploys get a 401 response code when trying to '
                      'download from the temporary URL, try raising this '
                      'duration. This value must be greater than or equal to '
                      'the value for '
                      'swift_temp_url_expected_download_start_delay')),
    cfg.BoolOpt('swift_temp_url_cache_enabled',
                default=False,
                help=_('Whether to cache generated Swift temporary URLs. '
                       'Setting it to true is only useful when an image '
                       'caching proxy is used. Defaults to False.')),
    cfg.IntOpt('swift_temp_url_expected_download_start_delay',
               default=0, min=0,
               help=_('This is the delay (in seconds) from the time of the '
                      'deploy request (when the Swift temporary URL is '
                      'generated) to when the IPA ramdisk starts up and URL '
                      'is used for the image download. This value is used to '
                      'check if the Swift temporary URL duration is large '
                      'enough to let the image download begin. Also if '
                      'temporary URL caching is enabled this will determine '
                      'if a cached entry will still be valid when the '
                      'download starts. swift_temp_url_duration value must be '
                      'greater than or equal to this option\'s value. '
                      'Defaults to 0.')),
    cfg.StrOpt(
        'swift_endpoint_url',
        help=_('The "endpoint" (scheme, hostname, optional port) for '
               'the Swift URL of the form '
               '"endpoint_url/api_version/[account/]container/object_id". '
               'Do not include trailing "/". '
               'For example, use "https://swift.example.com". If using RADOS '
               'Gateway, endpoint may also contain /swift path; if it does '
               'not, it will be appended. Required for temporary URLs.')),
    cfg.StrOpt(
        'swift_api_version',
        default='v1',
        help=_('The Swift API version to create a temporary URL for. '
               'Defaults to "v1". Swift temporary URL format: '
               '"endpoint_url/api_version/[account/]container/object_id"')),
    cfg.StrOpt(
        'swift_account',
        help=_('The account that Glance uses to communicate with '
               'Swift. The format is "AUTH_uuid". "uuid" is the '
               'UUID for the account configured in the glance-api.conf. '
               'Required for temporary URLs when Glance backend is Swift. '
               'For example: "AUTH_a422b2-91f3-2f46-74b7-d7c9e8958f5d30". '
               'Swift temporary URL format: '
               '"endpoint_url/api_version/[account/]container/object_id"')),
    cfg.StrOpt(
        'swift_container',
        default='glance',
        help=_('The Swift container Glance is configured to store its '
               'images in. Defaults to "glance", which is the default '
               'in glance-api.conf. '
               'Swift temporary URL format: '
               '"endpoint_url/api_version/[account/]container/object_id"')),
    cfg.IntOpt('swift_store_multiple_containers_seed',
               default=0,
               help=_('This should match a config by the same name in the '
                      'Glance configuration file. When set to 0, a '
                      'single-tenant store will only use one '
                      'container to store all images. When set to an integer '
                      'value between 1 and 32, a single-tenant store will use '
                      'multiple containers to store images, and this value '
                      'will determine how many containers are created.')),
    cfg.StrOpt('glance_host',
               help=_('Default glance hostname or IP address. The service '
                      'catalog is used when not defined. Deprecated, '
                      'use glance_api_servers instead.'),
               deprecated_for_removal=True),
    cfg.PortOpt('glance_port',
                default=9292,
                help=_('Default glance port. Deprecated, use '
                       'glance_api_servers instead.'),
                deprecated_for_removal=True),
    cfg.StrOpt('glance_protocol',
               default='http',
               choices=['http', 'https'],
               help=_('Default protocol to use when connecting to glance. '
                      'Set to https for SSL. Deprecated, use '
                      'glance_api_services instead.'),
               deprecated_for_removal=True),
    cfg.ListOpt('glance_api_servers',
                help=_('A list of the glance api servers available to ironic. '
                       'Prefix with https:// for SSL-based glance API '
                       'servers. Format is [hostname|IP]:port. If neither '
                       'this option nor glance_host is set, the service '
                       'catalog is used. It is recommended to rely on the '
                       'service catalog, if possible.')),
    cfg.BoolOpt('glance_api_insecure',
                default=False,
                help=_('Allow to perform insecure SSL (https) requests to '
                       'glance.')),
    cfg.IntOpt('glance_num_retries',
               default=0,
               help=_('Number of retries when downloading an image from '
                      'glance.')),
    cfg.StrOpt('auth_strategy',
               default='keystone',
               choices=['keystone', 'noauth'],
               help=_('Authentication strategy to use when connecting to '
                      'glance.')),
    cfg.StrOpt('glance_cafile',
               help=_('Optional path to a CA certificate bundle to be used to '
                      'validate the SSL certificate served by glance. It is '
                      'used when glance_api_insecure is set to False.')),
    cfg.IntOpt('glance_api_version',
               help=_('Glance API version (1 or 2) to use.'),
               min=1, max=2, default=2,
               deprecated_for_removal=True,
               deprecated_reason=_('Ironic will only support using Glance API '
                                   'version 2 in the Queens release.')),
]


def register_opts(conf):
    conf.register_opts(opts, group='glance')
    auth.register_auth_opts(conf, 'glance')


def list_opts():
    return auth.add_auth_opts(opts)
