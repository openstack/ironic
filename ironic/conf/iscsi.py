# Copyright 2016 Intel Corporation
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

opts = [
    cfg.PortOpt('portal_port',
                default=3260,
                help=_('The port number on which the iSCSI portal listens '
                       'for incoming connections.')),
    cfg.StrOpt('conv_flags',
               help=_('Flags that need to be sent to the dd command, '
                      'to control the conversion of the original file '
                      'when copying to the host. It can contain several '
                      'options separated by commas.')),
    # TODO(dtantsur): update in Ussuri when the deprecated option is removed
    # from ironic-lib.
    cfg.IntOpt('verify_attempts',
               min=1,
               help=_('Maximum attempts to verify an iSCSI connection is '
                      'active, sleeping 1 second between attempts. Defaults '
                      'to the deprecated [disk_utils]iscsi_verify_attempts '
                      'option, after its removal will default to 3.')),
]


def register_opts(conf):
    conf.register_opts(opts, group='iscsi')
