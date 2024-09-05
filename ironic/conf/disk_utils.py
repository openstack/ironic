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


# NOTE(TheJulia): If you make *any* chance to this code, you may need
# to make an identitical or similar change to ironic-python-agent.
# These options were  originally taken from ironic-lib upon the decision
# to move the qemu-img image conversion calls into the projects in
# order to simplify fixes related to them.
opts = [
    cfg.IntOpt('image_convert_memory_limit',
               default=2048,
               help='Memory limit for "qemu-img convert" in MiB. Implemented '
                    'via the address space resource limit.'),
    cfg.IntOpt('image_convert_attempts',
               default=3,
               help='Number of attempts to convert an image.'),
]


def register_opts(conf):
    conf.register_opts(opts, group='disk_utils')
