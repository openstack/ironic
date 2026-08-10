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
                help=_('Defines whether arbitrary containers are allowed for '
                       'use in the IPA ramdisk. If set to False, only '
                       'containers in the allowed_containers list can be '
                       'used. This applies to containers named in step '
                       'arguments, such as from a runbook or deploy '
                       'template; steps baked into the ramdisk at build time '
                       'are authored by the operator and are always '
                       'permitted.')),
    cfg.ListOpt('allowed_containers',
                default=[],
                help=_('List of allowed container images. Only used when '
                       'allow_arbitrary_containers is set to False. '
                       'Containers not in this list will be rejected.')),
    cfg.StrOpt('container_steps_file',
               default='/etc/ironic-python-agent.d/mysteps.yaml',
               help=_('Path in the ramdisk to the YAML file containing '
                      'container steps to be executed.')),
    cfg.StrOpt('runner',
               default='podman',
               choices=[('podman', _('use podman as the container runtime')),
                        ('docker', _('use docker as the container runtime'))],
               help=_('Container runtime to use in the agent ramdisk. Must '
                      'be a runtime the agent understands, otherwise the '
                      'agent ignores this value and keeps its own.')),
    cfg.ListOpt('pull_options',
                default=[],
                help=_('Options to pass when pulling container images, as a '
                       'comma separated list. The container runtime verifies '
                       'the registry certificate by default; '
                       '"--tls-verify=false" turns that off and is only '
                       'appropriate against a local test registry.')),
    cfg.ListOpt('run_options',
                default=['--rm', '--network=host'],
                help=_('Options to pass when running containers, as a comma '
                       'separated list (e.g. "--rm,--network=host"). The '
                       'runtime may pull the image at this point as well, so '
                       'the note on "--tls-verify=false" in pull_options '
                       'applies here too.')),
]


def register_opts(conf):
    conf.register_opts(opts, group='agent_containers')


def list_opts():
    return [opts]
