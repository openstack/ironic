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


group = cfg.OptGroup(name='oci',
                     title='OCI Container Registry Client Options')
opts = [
    cfg.ListOpt('secure_cdn_registries',
                default=[
                    'registry.redhat.io',
                    'registry.access.redhat.com',
                    'docker.io',
                    'registry-1.docker.io',
                ],
                # NOTE(TheJulia): Not a mutable option because this setting
                # impacts how the OCI client navigates configuration handling
                # for these hosts.
                mutable=False,
                help=_('An option which signals to the OCI Container Registry '
                       'client which remote endpoints are fronted by Content '
                       'Distribution Networks which we may receive redirects '
                       'to in order to download the requested artifacts, '
                       'where the OCI client should go ahead and issue the '
                       'download request with authentication headers before '
                       'being asked by the remote server for user '
                       'authentication.')),
    cfg.StrOpt('authentication_config',
               mutable=True,
               help=_('An option which allows pre-shared authorization keys '
                      'to be utilized by the Ironic service to facilitate '
                      'authentication with remote image registries which '
                      'may require authentication for all interactions. '
                      'Ironic will utilize these credentials to access '
                      'general artifacts, but Ironic will *also* prefer '
                      'user credentials, if supplied, for disk images. '
                      'This file is in the same format utilized in the '
                      'container ecosystem for the same purpose. '
                      'Structured as a JSON document with an ``auths`` '
                      'key, with remote registry domain FQDNs as keys, '
                      'and a nested ``auth`` key within that value which '
                      'holds the actual pre-shared secret. Ironic does '
                      'not cache the contents of this file at launch, '
                      'and the file can be updated as Ironic operates '
                      'in the event pre-shared tokens need to be '
                      'regenerated.')),
]


def register_opts(conf):
    conf.register_group(group)
    conf.register_opts(opts, group='oci')
