# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#    http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

from oslo_config import cfg

from ironic.common.i18n import _


opts = [
    cfg.BoolOpt('allow_arbitrary_containers',
                default=False,
                help=_('Defines whether arbitrary containers are allowed '
                       'for use in the IPA ramdisk. If set to False, only'
                       'containers in the allowed_containers list can'
                       ' be used.')),
    cfg.ListOpt('allowed_containers',
                default=[],
                help=_('List of allowed container images. Only used when '
                       'allow_arbitrary_containers is set to False.'
                       'Containers not in this list will be rejected.')),
    cfg.StrOpt('container_steps_file',
               default='/etc/ironic-python-agent.d/mysteps.yaml',
               help=_('Path in the ramdisk to the YAML file containing'
                      'container steps to be executed.')),
    cfg.StrOpt('runner',
               default='podman',
               help=_('Container runtime to use, such as'
                      '"podman" and "docker".')),
    cfg.StrOpt('pull_options',
               default='--tls-verify=false',
               help=_('Options to pass when pulling container images'
                      '(e.g., "--tls-verify=false").')),
    cfg.StrOpt('run_options',
               default='--rm --network=host --tls-verify=false',
               help=_('Options to pass when running containers'
                      '(e.g., "--rm --network=host").')),
    cfg.StrOpt('container_conf_file',
               default='/etc/containers/containers.conf',
               help=_('Path to the container configuration file'
                      'in the IPA ramdisk.'))
]


def register_opts(conf):
    conf.register_opts(opts, group='agent_containers')


def list_opts():
    return [opts]
