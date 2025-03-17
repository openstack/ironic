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

"""Utilities and helper functions for rules."""

from collections import abc

from ironic.common.i18n import _


class ShallowMaskList(abc.MutableSequence):
    """A proxy list to maintain original list and applies masking on the fly.

    This class implements the MutableSequence ABC to provide a complete
    list-like interface while handling sensitive data masking consistently
    with ShallowMaskDict.
    """
    def __init__(self, original_list, sensitive_fields=None,
                 mask_enabled=True):
        self._original = original_list
        self._sensitive_fields = sensitive_fields or []
        self._mask_enabled = mask_enabled

    def _mask_value(self, value):
        """Apply masking to value on demand."""
        if isinstance(value, dict):
            return ShallowMaskDict(
                value,
                sensitive_fields=self._sensitive_fields,
                mask_enabled=self._mask_enabled
            )
        elif isinstance(value, list):
            return ShallowMaskList(
                value,
                sensitive_fields=self._sensitive_fields,
                mask_enabled=self._mask_enabled
            )
        return value

    def __getitem__(self, index):
        value = self._original[index]
        return self._mask_value(value)

    def __setitem__(self, index, value):
        self._original[index] = value

    def __delitem__(self, index):
        del self._original[index]

    def __len__(self):
        return len(self._original)

    def insert(self, index, value):
        self._original.insert(index, value)

    def copy(self):
        return ShallowMaskList(
            self._original.copy(),
            sensitive_fields=self._sensitive_fields,
            mask_enabled=self._mask_enabled
        )

    def set_mask_enabled(self, mask_enabled):
        self._mask_enabled = mask_enabled

    def __repr__(self):
        items = [repr(self._mask_value(item)) for item in self._original]
        return "[%s]" % ", ".join(items)


class ShallowMaskDict(abc.MutableMapping):
    """Dictionary wrapper to mask sensitive fields on the fly.

    This class implements the MutableMapping ABC to provide a complete
    dict-like interface while masking sensitive fields when accessed.
    """
    def __init__(self, data, sensitive_fields=None, mask_enabled=True):
        self._data = data
        self._sensitive_fields = sensitive_fields or []
        self._mask_enabled = mask_enabled

    def _mask_value(self, key, value):
        if self._mask_enabled and key in self._sensitive_fields:
            return '***'

        if isinstance(value, dict):
            return ShallowMaskDict(
                value,
                sensitive_fields=self._sensitive_fields,
                mask_enabled=self._mask_enabled
            )
        elif isinstance(value, list):
            return ShallowMaskList(
                value,
                sensitive_fields=self._sensitive_fields,
                mask_enabled=self._mask_enabled
            )
        return value

    def __getitem__(self, key):
        value = self._data[key]
        return self._mask_value(key, value)

    def __setitem__(self, key, value):
        self._data[key] = value

    def __delitem__(self, key):
        del self._data[key]

    def __iter__(self):
        return iter(self._data)

    def __len__(self):
        return len(self._data)

    def copy(self):
        return ShallowMaskDict(
            self._data.copy(),
            sensitive_fields=self._sensitive_fields,
            mask_enabled=self._mask_enabled,
        )

    def set_mask_enabled(self, mask_enabled):
        self._mask_enabled = mask_enabled

    def __repr__(self):
        items = ["%s: %s" % (repr(k), repr(self._mask_value(k, v)))
                 for k, v in self._data.items()]
        return "{%s}" % ", ".join(items)


def parse_inverted_operator(op):
    """Handle inverted operators.

    Parses a logical condition operator to determine if it has been negated
    using a single leading exclamation mark ('!'). Ensures only one
    exclamation mark is allowed.

    Example Usage:
        parse_inverted_operator("!eq")   # Returns ("eq", True)
        parse_inverted_operator(" eq ")  # Returns ("eq", False)
        parse_inverted_operator("!!eq")  # Raises ValueError

    raises: ValueError: If multiple exclamation marks are present
    returns: A tuple containing the cleaned operator and a
            boolean indicating whether negation was applied.
    """
    op = op.strip()

    if op.count('!') > 1:
        msg = _("Multiple exclamation marks are not allowed. "
                "To apply the invert of an operation, simply add an "
                "exclamation mark (with an optional space) before "
                "the operator, e.g. eq - !eq.")
        raise ValueError(msg)

    is_inverted = op.startswith('!')
    op = op.lstrip('!').strip()
    return op, is_inverted


def normalize_path(path):
    """Convert a path (dot or slash notation) to a list of path parts"""
    if '/' in path:
        parts = path.strip('/').split('/')
    else:
        parts = path.split('.')
    return parts
