# -*- encoding: utf-8 -*-
#
# Copyright © 2012 New Dream Network, LLC (DreamHost)
#
# Author: Doug Hellmann <doug.hellmann@dreamhost.com>
#
# Licensed under the Apache License, Version 2.0 (the "License"); you may
# not use this file except in compliance with the License. You may obtain
# a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
# WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
# License for the specific language governing permissions and limitations
# under the License.
"""
Base class for plugin loader.
"""

from stevedore import enabled

from ironic.openstack.common import log


LOG = log.getLogger(__name__)


def should_use_extension(namespace, ext, enabled_names):
    """Return boolean indicating whether the extension should be used.

    Tests the extension against a couple of criteria to see whether it
    should be used, logs the reason it is not used if not, and then
    returns the result.
    """
    if ext.name not in enabled_names:
        LOG.debug(
            '%s extension %r disabled through configuration setting',
            namespace, ext.name,
        )
        return False
    if not ext.obj.is_enabled():
        LOG.debug(
            '%s extension %r reported that it is disabled',
            namespace,
            ext.name,
        )
        return False
    LOG.debug('using %s extension %r', namespace, ext.name)
    return True


class ActivatedExtensionManager(enabled.EnabledExtensionManager):
    """Loads extensions based on a configurable set that should be
    disabled and asking each one if it should be active or not.
    """

    def __init__(self, namespace, enabled_names, invoke_on_load=True,
                 invoke_args=(), invoke_kwds={}):

        def local_check_func(ext):
            return should_use_extension(namespace, ext, enabled_names)

        super(ActivatedExtensionManager, self).__init__(
            namespace=namespace,
            check_func=local_check_func,
            invoke_on_load=invoke_on_load,
            invoke_args=invoke_args,
            invoke_kwds=invoke_kwds,
        )
