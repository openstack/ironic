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

opts = [
    cfg.IntOpt('query_raid_config_job_status_interval',
               default=120,
               help=_('Interval (in seconds) between periodic RAID job status '
                      'checks to determine whether the asynchronous RAID '
                      'configuration was successfully finished or not.'))
]


def register_opts(conf):
    conf.register_opts(opts, group='drac')
