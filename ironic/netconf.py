# Copyright 2010 United States Government as represented by the
# Administrator of the National Aeronautics and Space Administration.
# All Rights Reserved.
# Copyright 2012 Red Hat, Inc.
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
from oslo_utils import netutils

from ironic.common.i18n import _

CONF = cfg.CONF

netconf_opts = [
    cfg.StrOpt('my_ip',
               default=netutils.get_my_ipv4(),
               sample_default='127.0.0.1',
               help=_('IP address of this host. If unset, will determine the '
                      'IP programmatically. If unable to do so, will use '
                      '"127.0.0.1".')),
]

CONF.register_opts(netconf_opts)
