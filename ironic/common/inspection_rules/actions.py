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

import abc
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from oslo_log import log

from ironic.common import exception
from ironic.common.i18n import _
from ironic.common.inspection_rules import base
from ironic.common.inspection_rules import utils
from ironic.drivers import utils as driver_utils
from ironic import objects


LOG = log.getLogger(__name__)
ACTIONS = {
    "fail": "FailAction",
    "set-attribute": "SetAttributeAction",
    "set-capability": "SetCapabilityAction",
    "unset-capability": "UnsetCapabilityAction",
    "extend-attribute": "ExtendAttributeAction",
    "add-trait": "AddTraitAction",
    "remove-trait": "RemoveTraitAction",
    "set-plugin-data": "SetPluginDataAction",
    "extend-plugin-data": "ExtendPluginDataAction",
    "unset-plugin-data": "UnsetPluginDataAction",
    "log": "LogAction",
    "del-attribute": "DelAttributeAction",
    "set-port-attribute": "SetPortAttributeAction",
    "extend-port-attribute": "ExtendPortAttributeAction",
    "del-port-attribute": "DelPortAttributeAction",
    "api-call": "CallAPIHookAction",
}


def get_action(op_name):
    """Get operator class by name."""
    if op_name not in ACTIONS:
        raise exception.Invalid(
            _("Unsupported action '%s'.") % op_name
        )
    class_name = ACTIONS[op_name]
    return globals()[class_name]


def update_nested_dict(d, key_path, value):
    keys = key_path.split('.') if isinstance(key_path, str) else key_path
    current = d
    for key in keys[:-1]:
        current = current.setdefault(key, {})
    current[keys[-1]] = value
    return d


class ActionBase(base.Base, metaclass=abc.ABCMeta):
    """Abstract base class for rule action plugins."""

    FORMATTED_ARGS = []
    """List of params to be formatted with python format."""

    @abc.abstractmethod
    def __call__(self, task, *args, **kwargs):
        """Run action on successful rule match."""

    def execute_with_loop(self, task, action, inventory, plugin_data):
        loop_items = None
        if action.get('loop', []):
            loop_items = action['loop']

        if isinstance(loop_items, (list, dict)):
            if isinstance(loop_items, dict):
                loop_context = {'item': loop_items}
                action_copy = action.copy()
                self.execute_action(task, action_copy, inventory, plugin_data,
                                    loop_context)
                return

            for item in loop_items:
                loop_context = {'item': item}
                action_copy = action.copy()
                self.execute_action(task, action_copy, inventory, plugin_data,
                                    loop_context)

    def execute_action(self, task, action, inventory, plugin_data,
                       loop_context=None):
        processed_args = self._process_args(task, action, inventory,
                                            plugin_data, loop_context)

        return self(task, **processed_args)


class LogAction(ActionBase):

    FORMATTED_ARGS = ['msg']
    VALID_LOG_LEVELS = {'debug', 'info', 'warning', 'error', 'critical'}

    def __call__(self, task, msg, level='info'):
        level = level.lower()
        if level not in self.VALID_LOG_LEVELS:
            raise exception.InspectionRuleExecutionFailure(
                _("Invalid log level: %(level)s. Choose from %(levels)s") % {
                    'level': level, 'levels': self.VALID_LOG_LEVELS})
        getattr(LOG, level)(msg)


class FailAction(ActionBase):

    def __call__(self, task, msg):
        raise exception.HardwareInspectionFailure(error=str(msg))


class SetAttributeAction(ActionBase):

    FORMATTED_ARGS = ['value']

    def __call__(self, task, path, value):
        try:
            attr_path_parts = utils.normalize_path(path)
            if len(attr_path_parts) == 1:
                setattr(task.node, attr_path_parts[0], value)
            else:
                base_attr = getattr(task.node, attr_path_parts[0])
                current = base_attr
                for part in attr_path_parts[1:-1]:
                    current = current.setdefault(part, {})
                current[attr_path_parts[-1]] = value
                setattr(task.node, attr_path_parts[0], base_attr)
            task.node.save()
        except Exception as exc:
            msg = _("Failed to set attribute %(path)s "
                    "with value %(value)s: %(exc)s") % {
                        'path': path, 'value': value, 'exc': exc}
            LOG.error(msg)
            raise exception.RuleActionExecutionFailure(reason=msg)


class ExtendAttributeAction(ActionBase):

    FORMATTED_ARGS = ['value']

    def __call__(self, task, path, value, unique=False):
        try:
            attr_path_parts = utils.normalize_path(path)
            if len(attr_path_parts) == 1:
                current = getattr(task.node, attr_path_parts[0], [])
            else:
                base_attr = getattr(task.node, attr_path_parts[0])
                current = base_attr
                for part in attr_path_parts[1:-1]:
                    current = current.setdefault(part, {})
                current = current.setdefault(attr_path_parts[-1], [])

            if not isinstance(current, list):
                msg = _("Cannot extend non-list attribute %(path)s with "
                        "value %(value)s") % {'path': path, 'value': value}
                raise exception.RuleActionExecutionFailure(reason=msg)
            if not unique or value not in current:
                current.append(value)

            if len(attr_path_parts) == 1:
                setattr(task.node, attr_path_parts[0], current)
            else:
                setattr(task.node, attr_path_parts[0], base_attr)
            task.node.save()
        except Exception as exc:
            msg = _("Failed to extend attribute %(path)s: %(exc)s") % {
                'path': path, 'exc': exc}
            raise exception.RuleActionExecutionFailure(reason=msg)


class DelAttributeAction(ActionBase):

    def __call__(self, task, path):
        try:
            attr_path_parts = utils.normalize_path(path)
            if len(attr_path_parts) == 1:
                delattr(task.node, attr_path_parts[0])
            else:
                base_attr = getattr(task.node, attr_path_parts[0])
                current = base_attr
                for part in attr_path_parts[1:-1]:
                    current = current[part]
                del current[attr_path_parts[-1]]
                setattr(task.node, attr_path_parts[0], base_attr)
            task.node.save()
        except Exception as exc:
            msg = _("Failed to delete attribute at %(path)s: %(exc)s") % {
                'path': path, 'exc': exc}
            raise exception.RuleActionExecutionFailure(reason=msg)


class AddTraitAction(ActionBase):

    def __call__(self, task, name):
        try:
            new_trait = objects.Trait(task.context, node_id=task.node.id,
                                      trait=name)
            new_trait.create()
        except Exception as exc:
            msg = _("Failed to add new trait %(name)s: %(exc)s") % {
                'name': name, 'exc': exc}
            raise exception.RuleActionExecutionFailure(reason=msg)


class RemoveTraitAction(ActionBase):

    def __call__(self, task, name):
        try:
            objects.Trait.destroy(task.context, node_id=task.node.id,
                                  trait=name)
        except exception.NodeTraitNotFound as exc:
            LOG.warning(_("Failed to remove trait %(name)s: %(exc)s"),
                        {'name': name, 'exc': exc})
        except Exception as exc:
            msg = _("Failed to remove trait %(name)s: %(exc)s") % {
                'name': name, 'exc': exc}
            raise exception.RuleActionExecutionFailure(reason=msg)


class SetCapabilityAction(ActionBase):

    FORMATTED_ARGS = ['value']

    def __call__(self, task, name, value):
        try:
            driver_utils.add_node_capability(task, name, value)
        except Exception as exc:
            msg = _("Failed to set capability %(name)s: %(exc)s") % {
                'name': name, 'exc': exc}
            raise exception.RuleActionExecutionFailure(
                reason=msg)


class UnsetCapabilityAction(ActionBase):

    def __call__(self, task, name):
        try:
            driver_utils.remove_node_capability(task, name)
        except Exception as exc:
            msg = _("Failed to unset capability %(name)s: %(exc)s") % {
                'name': name, 'exc': exc}
            raise exception.RuleActionExecutionFailure(reason=msg)


class SetPluginDataAction(ActionBase):

    REQUIRES_PLUGIN_DATA = True
    FORMATTED_ARGS = ['value']

    def __call__(self, task, path, value, plugin_data):
        try:
            update_nested_dict(plugin_data, path, value)
        except Exception as exc:
            msg = _("Failed to set plugin data at %(path)s: %(exc)s") % {
                'path': path, 'exc': exc}
            raise exception.RuleActionExecutionFailure(reason=msg)


class ExtendPluginDataAction(ActionBase):

    REQUIRES_PLUGIN_DATA = True
    FORMATTED_ARGS = ['value']

    def __call__(self, task, path, value, plugin_data, unique=False):
        try:
            current = self._get_nested_value(plugin_data, path) or []
            update_nested_dict(plugin_data, path, current)
            if not unique or (value not in current):
                current.append(value)
        except Exception as exc:
            msg = _("Failed to extend plugin data at %(path)s: %(exc)s") % {
                'path': path, 'exc': exc}
            raise exception.RuleActionExecutionFailure(reason=msg)

    @staticmethod
    def _get_nested_value(d, key_path, default=None):
        keys = key_path.split('.') if isinstance(key_path, str) else key_path
        current = d
        try:
            for key in keys:
                current = current[key]
            return current
        except (KeyError, TypeError):
            return default


class UnsetPluginDataAction(ActionBase):

    REQUIRES_PLUGIN_DATA = True

    def __call__(self, task, path, plugin_data):
        try:
            if not self._unset_nested_dict(plugin_data, path):
                LOG.warning("Path %s not found", path)
        except Exception as exc:
            msg = _("Failed to unset plugin data at %(path)s: %(exc)s") % {
                'path': path, 'exc': exc}
            raise exception.RuleActionExecutionFailure(reason=msg)

    @staticmethod
    def _unset_nested_dict(d, key_path):
        keys = key_path.split('.') if isinstance(key_path, str) else key_path
        current = d
        for key in keys[:-1]:
            if not isinstance(current, dict) or key not in current:
                return False
            current = current[key]

        target_key = keys[-1]
        if isinstance(current, dict) and target_key in current:
            if len(current) == 1:
                parent = d
                for key in keys[:-2]:
                    parent = parent[key]
                if len(keys) > 1:
                    del parent[keys[-2]]
            else:
                del current[target_key]
            return True
        return False


class SetPortAttributeAction(ActionBase):

    FORMATTED_ARGS = ['value']

    def __call__(self, task, port_id, path, value):
        port = next((p for p in task.ports if p.uuid == port_id), None)
        if not port:
            raise exception.PortNotFound(port=port_id)
        try:
            attr_path_parts = utils.normalize_path(path)
            if len(attr_path_parts) == 1:
                setattr(port, attr_path_parts[0], value)
            else:
                base_attr = getattr(port, attr_path_parts[0])
                current = base_attr
                for part in attr_path_parts[1:-1]:
                    current = current.setdefault(part, {})
                current[attr_path_parts[-1]] = value
                setattr(port, attr_path_parts[0], base_attr)
            port.save()
        except Exception as exc:
            msg = _("Failed to set attribute %(path)s for port "
                    "%(port_id)s: %(exc)s") % {
                        'path': path, 'port_id': port_id, 'exc': exc}
            LOG.error(msg)
            raise exception.RuleActionExecutionFailure(reason=msg)


class ExtendPortAttributeAction(ActionBase):

    FORMATTED_ARGS = ['value']

    def __call__(self, task, port_id, path, value, unique=False):
        port = next((p for p in task.ports if p.uuid == port_id), None)
        if not port:
            raise exception.PortNotFound(port=port_id)
        try:
            attr_path_parts = utils.normalize_path(path)
            if len(attr_path_parts) == 1:
                current = getattr(port, attr_path_parts[0], [])
            else:
                base_attr = getattr(port, attr_path_parts[0])
                current = base_attr
                for part in attr_path_parts[1:-1]:
                    current = current.setdefault(part, {})
                current = current.setdefault(attr_path_parts[-1], [])

            if not isinstance(current, list):
                msg = (_("Cannot extend non-list attribute %(path)s with "
                         " value %(value)s") % {'path': path, 'value': value})
                raise exception.RuleActionExecutionFailure(reason=msg)
            if not unique or value not in current:
                current.append(value)

            if len(attr_path_parts) == 1:
                setattr(port, attr_path_parts[0], current)
            else:
                setattr(port, attr_path_parts[0], base_attr)
            port.save()
        except Exception as exc:
            msg = _("Failed to extend attribute %(path)s for port "
                    "%(port_id)s: %(exc)s") % {
                        'path': path, 'port_id': port_id, 'exc': exc}
            LOG.error(msg)
            raise exception.RuleActionExecutionFailure(reason=msg)


class DelPortAttributeAction(ActionBase):

    def __call__(self, task, port_id, path):
        port = next((p for p in task.ports if p.uuid == port_id), None)
        if not port:
            raise exception.PortNotFound(port=port_id)
        try:
            attr_path_parts = utils.normalize_path(path)
            if len(attr_path_parts) == 1:
                delattr(port, attr_path_parts[0])
            else:
                base_attr = getattr(port, attr_path_parts[0])
                current = base_attr
                for part in attr_path_parts[1:-1]:
                    current = current[part]
                del current[attr_path_parts[-1]]
                setattr(port, attr_path_parts[0], base_attr)
            port.save()
        except Exception as exc:
            msg = ("Failed to delete attribute %(path)s for port "
                   "%(port_id)s: %(exc)s") % {
                       'path': path, 'port_id': port_id, 'exc': str(exc)}
            LOG.error(msg)
            raise exception.RuleActionExecutionFailure(reason=msg)


class CallAPIHookAction(ActionBase):
    FORMATTED_ARGS = ['url']
    OPTIONAL_PARAMS = [
        'headers', 'proxies', 'timeout', 'retries', 'backoff_factor'
    ]

    def __call__(self, task, url, headers=None, proxies=None,
                 timeout=5, retries=3, backoff_factor=0.3):
        try:
            timeout = float(timeout)
            if timeout <= 0:
                raise ValueError("timeout must be greater than zero")
            retries = int(retries)
            backoff_factor = float(backoff_factor)
            retry_strategy = Retry(
                total=retries,
                backoff_factor=backoff_factor,
                status_forcelist=[429, 500, 502, 503, 504],
                allowed_methods=["GET"],
                raise_on_status=False
            )
            adapter = HTTPAdapter(max_retries=retry_strategy)
            session = requests.Session()
            session.mount("http://", adapter)
            session.mount("https://", adapter)
            request_kwargs = {}
            if headers:
                request_kwargs['headers'] = headers
            if proxies:
                request_kwargs['proxies'] = proxies
            response = session.get(url, timeout=timeout, **request_kwargs)
            response.raise_for_status()
        except ValueError as exc:
            msg = _("Invalid parameter: %s") % exc
            LOG.error(msg)
            raise exception.RuleActionExecutionFailure(reason=msg)
        except requests.exceptions.RequestException as exc:
            msg = _("Request to %(url)s failed: %(exc)s") % {
                'url': url, 'exc': exc}
            LOG.error(msg)
            raise exception.RuleActionExecutionFailure(reason=msg)
