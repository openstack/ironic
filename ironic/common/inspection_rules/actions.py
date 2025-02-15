
# Copyright 2013 Red Hat, Inc.
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

import abc

from oslo_log import log

from ironic.common import exception
from ironic.common.i18n import _
from ironic.common.inspection_rules import base
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
}


def get_action(op_name):
    """Get operator class by name."""
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

    OPTIONAL_ARGS = set()
    """Set with names of optional parameters."""

    FORMATTED_ARGS = []
    """List of params to be formatted with python format."""

    @abc.abstractmethod
    def __call__(self, task, *args, **kwargs):
        """Run action on successful rule match."""

    def _execute_with_loop(self, task, action, inventory, plugin_data):
        loop_items = action.get('loop', [])
        results = []

        if isinstance(loop_items, (list, dict)):
            for item in loop_items:
                action_copy = action.copy()
                action_copy['args'] = item
                results.append(self._execute_action(task, action_copy,
                                                    inventory, plugin_data))
        return results

    def _execute_action(self, task, action, inventory, plugin_data):
        processed_args = self._process_args(task, action, inventory,
                                            plugin_data)

        arg_values = [processed_args[arg_name]
                      for arg_name in self.get_arg_names()]

        for optional_arg in self.OPTIONAL_ARGS:
            arg_values.append(processed_args.get(optional_arg, False))

        return self(task, *arg_values)


class LogAction(ActionBase):
    FORMATTED_ARGS = ['msg']

    @classmethod
    def get_arg_names(cls):
        return ['msg']

    def __call__(self, task, msg, level='info'):
        getattr(LOG, level)(msg)


class FailAction(ActionBase):

    @classmethod
    def get_arg_names(cls):
        return ['msg']

    def __call__(self, task, msg):
        msg = _('%(msg)s') % {'msg': msg}
        raise exception.HardwareInspectionFailure(error=msg)


class SetAttributeAction(ActionBase):
    FORMATTED_ARGS = ['value']

    @classmethod
    def get_arg_names(cls):
        return ['path', 'value']

    def __call__(self, task, path, value):
        try:
            attr_path_parts = path.strip('/').split('/')
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
            msg = ("Failed to set attribute %(path)s "
                   "with value %(value)s: %(exc)s" %
                   {'path': path, 'value': value, 'exc': exc})
            LOG.error(msg)
            raise exception.InvalidParameterValue(msg)


class ExtendAttributeAction(ActionBase):

    OPTIONAL_ARGS = {'unique'}
    FORMATTED_ARGS = ['value']

    @classmethod
    def get_arg_names(cls):
        return ['path', 'value']

    def __call__(self, task, path, value, unique=False):
        try:
            attr_path_parts = path.strip('/').split('/')
            if len(attr_path_parts) == 1:
                current = getattr(task.node, attr_path_parts[0], [])
            else:
                base_attr = getattr(task.node, attr_path_parts[0])
                current = base_attr
                for part in attr_path_parts[1:-1]:
                    current = current.setdefault(part, {})
                current = current.setdefault(attr_path_parts[-1], [])

            if not isinstance(current, list):
                current = []
            if not unique or value not in current:
                current.append(value)

            if len(attr_path_parts) == 1:
                setattr(task.node, attr_path_parts[0], current)
            else:
                setattr(task.node, attr_path_parts[0], base_attr)
            task.node.save()
        except Exception as exc:
            msg = ("Failed to extend attribute %(path)s: %(exc)s") % {
                'path': path, 'exc': exc}
            raise exception.InvalidParameterValue(msg)


class DelAttributeAction(ActionBase):

    @classmethod
    def get_arg_names(cls):
        return ['path']

    def __call__(self, task, path):
        try:
            attr_path_parts = path.strip('/').split('/')
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
            msg = ("Failed to delete attribute at %(path)s: %(exc)s") % {
                'path': path, 'exc': exc}
            raise exception.InvalidParameterValue(msg)


class AddTraitAction(ActionBase):

    @classmethod
    def get_arg_names(cls):
        return ['name']

    def __call__(self, task, name):
        try:
            new_trait = objects.Trait(task.context, node_id=task.node.id,
                                      trait=name)
            new_trait.create()
        except Exception as exc:
            msg = (_("Failed to add new trait %(name)s: %(exc)s") %
                   {'name': name, 'exc': exc})
            raise exception.InvalidParameterValue(msg)


class RemoveTraitAction(ActionBase):

    @classmethod
    def get_arg_names(cls):
        return ['name']

    def __call__(self, task, name):
        try:
            objects.Trait.destroy(task.context, node_id=task.node.id,
                                  trait=name)
        except exception.NodeTraitNotFound as exc:
            LOG.warning(_("Failed to remove trait %(name)s: %(exc)s"),
                        {'name': name, 'exc': exc})
        except Exception as exc:
            msg = (_("Failed to remove trait %(name)s: %(exc)s") %
                   {'name': name, 'exc': exc})
            raise exception.InvalidParameterValue(msg)


class SetCapabilityAction(ActionBase):
    FORMATTED_ARGS = ['value']

    @classmethod
    def get_arg_names(cls):
        return ['name', 'value']

    def __call__(self, task, name, value):
        try:
            properties = task.node.properties.copy()
            capabilities = properties.get('capabilities', '')
            caps = dict(cap.split(':', 1)
                        for cap in capabilities.split(',') if cap)
            caps[name] = value
            properties['capabilities'] = ','.join('%s:%s' % (k, v)
                                                  for k, v in caps.items())
            task.node.properties = properties
            task.node.save()
        except Exception as exc:
            raise exception.InvalidParameterValue(
                "Failed to set capability %(name)s: %(exc)s" %
                {'name': name, 'exc': exc})


class UnsetCapabilityAction(ActionBase):
    @classmethod
    def get_arg_names(cls):
        return ['name']

    def __call__(self, task, name):
        try:
            properties = task.node.properties.copy()
            capabilities = properties.get('capabilities', '')
            caps = dict(cap.split(':', 1)
                        for cap in capabilities.split(',') if cap)
            caps.pop(name, None)
            properties['capabilities'] = ','.join('%s:%s' % (k, v)
                                                  for k, v in caps.items())
            task.node.properties = properties
            task.node.save()
        except Exception as exc:
            raise exception.InvalidParameterValue(
                "Failed to unset capability %(name)s: %(exc)s" %
                {'name': name, 'exc': exc})


class SetPluginDataAction(ActionBase):

    FORMATTED_ARGS = ['value']

    @classmethod
    def get_arg_names(cls):
        return ['path', 'value', 'plugin_data']

    def __call__(self, task, path, value, plugin_data):
        try:
            update_nested_dict(plugin_data, path, value)
            return {'plugin_data': plugin_data}
        except Exception as exc:
            msg = ("Failed to set plugin data at %(path)s: %(exc)s" % {
                'path': path, 'exc': exc})
            raise exception.InvalidParameterValue(msg)


class ExtendPluginDataAction(ActionBase):

    OPTIONAL_ARGS = {'unique'}
    FORMATTED_ARGS = ['value']

    @classmethod
    def get_arg_names(cls):
        return ['path', 'value', 'plugin_data']

    def __call__(self, task, path, value, plugin_data, unique=False):
        try:
            current = self._get_nested_value(plugin_data, path)
            if current is None:
                current = []
                update_nested_dict(plugin_data, path, current)
            elif not isinstance(current, list):
                current = []
                update_nested_dict(plugin_data, path, current)
            if not unique or value not in current:
                current.append(value)
            return {'plugin_data': plugin_data}
        except Exception as exc:
            msg = ("Failed to extend plugin data at %(path)s: %(exc)s") % {
                'path': path, 'exc': exc}
            raise exception.InvalidParameterValue(msg)

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

    @classmethod
    def get_arg_names(cls):
        return ['path', 'plugin_data']

    def __call__(self, task, path, plugin_data):
        try:
            if not self._unset_nested_dict(plugin_data, path):
                LOG.warning("Path %s not found", path)
            return {'plugin_data': plugin_data}
        except Exception as exc:
            msg = ("Failed to unset plugin data at %(path)s: %(exc)s") % {
                'path': path, 'exc': exc}
            raise exception.InvalidParameterValue(msg)

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

    @classmethod
    def get_arg_names(cls):
        return ['port_id', 'path', 'value']

    def __call__(self, task, port_id, path, value):
        port = next((p for p in task.ports if p.uuid == port_id), None)
        if not port:
            raise exception.PortNotFound(port=port_id)
        try:
            attr_path_parts = path.strip('/').split('/')
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
            msg = ("Failed to set attribute %(path)s for port "
                   "%(port_id)s: %(exc)s") % {'path': path,
                                              'port_id': port_id,
                                              'exc': str(exc)}
            LOG.warning(msg)


class ExtendPortAttributeAction(ActionBase):
    OPTIONAL_ARGS = {'unique'}
    FORMATTED_ARGS = ['value']

    @classmethod
    def get_arg_names(cls):
        return ['port_id', 'path', 'value']

    def __call__(self, task, port_id, path, value, unique=False):
        port = next((p for p in task.ports if p.uuid == port_id), None)
        if not port:
            raise exception.PortNotFound(port=port_id)
        try:
            attr_path_parts = path.strip('/').split('/')
            if len(attr_path_parts) == 1:
                current = getattr(port, attr_path_parts[0], [])
            else:
                base_attr = getattr(port, attr_path_parts[0])
                current = base_attr
                for part in attr_path_parts[1:-1]:
                    current = current.setdefault(part, {})
                current = current.setdefault(attr_path_parts[-1], [])

            if not isinstance(current, list):
                current = []
            if not unique or value not in current:
                current.append(value)

            if len(attr_path_parts) == 1:
                setattr(port, attr_path_parts[0], current)
            else:
                setattr(port, attr_path_parts[0], base_attr)
            port.save()
        except Exception as exc:
            msg = ("Failed to extend attribute %(path)s for port "
                   "%(port_id)s: %(exc)s") % {'path': path,
                                              'port_id': port_id,
                                              'exc': str(exc)}
            LOG.warning(msg)


class DelPortAttributeAction(ActionBase):

    @classmethod
    def get_arg_names(cls):
        return ['port_id', 'path']

    def __call__(self, task, port_id, path):
        port = next((p for p in task.ports if p.uuid == port_id), None)
        if not port:
            raise exception.PortNotFound(port=port_id)
        try:
            attr_path_parts = path.strip('/').split('/')
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
                   "%(port_id)s: %(exc)s") % {'path': path,
                                              'port_id': port_id,
                                              'exc': str(exc)}
            LOG.warning(msg)
