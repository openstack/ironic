# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#    http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or
# implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Base code for inspection hooks support."""

import abc

from oslo_config import cfg
from oslo_log import log
import stevedore

from ironic.common import exception
from ironic.common.i18n import _

CONF = cfg.CONF
LOG = log.getLogger(__name__)
_HOOKS_MGR = None


class InspectionHook(metaclass=abc.ABCMeta):  # pragma: no cover
    """Abstract base class for inspection hooks."""

    dependencies = []
    """An ordered list of hooks that must be enabled before this one.

    The items here should be entry point names, not classes.
    """

    def preprocess(self, task, inventory, plugin_data):
        """Hook to run before the main inspection data processing.

        This hook is run even before sanity checks.

        :param task: A TaskManager instance.
        :param inventory: Hardware inventory information sent by the ramdisk.
                          Must not be modified by the hook.
        :param plugin_data: Plugin data sent by the ramdisk. May be modified by
                            the hook.
        :returns: nothing.
        """

    def __call__(self, task, inventory, plugin_data):
        """Hook to run to process inspection data (before Ironic node update).

        This hook is run after node is found and ports are created,
        just before the node is updated with the data.

        :param task: A TaskManager instance.
        :param inventory: Hardware inventory information sent by the ramdisk.
                          Must not be modified by the hook.
        :param plugin_data: Plugin data sent by the ramdisk. May be modified by
                            the hook.
        :returns: nothing.
        """


def reset():
    """Reset cached managers."""
    global _HOOKS_MGR

    _HOOKS_MGR = None


def missing_entrypoints_callback(names):
    """Raise RuntimeError with comma-separated list of missing hooks"""
    error = _('The following hook(s) are missing or failed to load: %s')
    raise RuntimeError(error % ', '.join(names))


def inspection_hooks_manager(*args):
    """Create a Stevedore extension manager for inspection hooks.

    :param args: arguments to pass to the hooks constructor
    :returns: a Stevedore NamedExtensionManager
    """
    global _HOOKS_MGR
    if _HOOKS_MGR is None:
        enabled_hooks = [x.strip()
                         for x in CONF.inspector.hooks.split(',')
                         if x.strip()]
        _HOOKS_MGR = stevedore.NamedExtensionManager(
            'ironic.inspection.hooks',
            names=enabled_hooks,
            invoke_on_load=True,
            invoke_args=args,
            on_missing_entrypoints_callback=missing_entrypoints_callback,
            name_order=True)
    return _HOOKS_MGR


def validate_inspection_hooks():
    """Validate the enabled inspection hooks.

    :raises: RuntimeError on missing or failed to load hooks
    :returns: the list of hooks that passed validation
    """
    conf_hooks = [ext for ext in inspection_hooks_manager()]
    valid_hooks = []
    valid_hook_names = set()
    errors = []

    for hook in conf_hooks:
        deps = getattr(hook.obj, 'dependencies', ())
        missing = [d for d in deps if d not in valid_hook_names]
        if missing:
            errors.append('Hook %(hook)s requires these missing hooks to be '
                          'enabled before it: %(missing)s' %
                          {'hook': hook.name, 'missing': ', '.join(missing)})
        else:
            valid_hooks.append(hook)
            valid_hook_names.add(hook.name)

    if errors:
        msg = _('Some hooks failed to load due to dependency problems: '
                '%(errors)s') % {'errors': ', '.join(errors)}
        LOG.error(msg)
        raise exception.HardwareInspectionFailure(error=msg)

    return valid_hooks
