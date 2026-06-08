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

import lark

from dataclasses import dataclass

from ironic.common.exception import InvalidParameterValue
from ironic.common.i18n import _


def sanitize_kernel_command_line(command_line: str) -> str:
    """Applies filtering to a command line to sanitize it.

    NOTE: This does not guarantee a correct or safe kernel command line,
    for stronger guarantees of correctness and safety use
    KernelCommandLine.parse().

    :param command_line: A string containing a kernel command line or
        individual parameters.
    :returns: A filtered string which should be safer for use.
    """
    return ''.join(c for c in command_line if c not in {'\n', '\r', '\0'})


@dataclass(frozen=True)
class ParameterKey:
    key: str

    def __str__(self):
        return self.key


@dataclass(frozen=True)
class ParameterValue:
    value: str

    def __str__(self):
        if ' ' in self.value:
            return f"\"{self.value}\""
        return self.value


@dataclass(frozen=True)
class KernelParameter:
    key: ParameterKey
    value: ParameterValue

    def __str__(self):
        if len(self.value.value) > 0:
            return f"{self.key}={self.value}"
        return self.key.key


@dataclass(frozen=True)
class KernelCommandLine:
    parameters: dict[str, list[KernelParameter]]
    init_args: str

    def __str__(self):
        output = ' '.join(
            ' '.join(str(param) for param in param_list)
            for param_list in self.parameters.values())
        if len(self.init_args) > 0:
            output += " -- " + self.init_args
        return output

    @classmethod
    def parse(cls, command_line: str):
        try:
            tree = KernelParameterParser.parse(command_line.strip())
            return KernelParameterTransformer().transform(tree)
        except (lark.exceptions.LarkError,
                lark.exceptions.UnexpectedInput) as e:
            raise InvalidParameterValue(
                _('Kernel command line did not parse: "%s" -- %s') \
                % (command_line, str(e))) from None


# NOTE(clif): Some valid values (such as filenames) are not going to be
# representable given we're explicitly not allowing large swaths characters
# in parameter values. I believe this is reasonable. Most people do not
# purposefully put non-printable/control characters in kernel parameters for
# anything other than nefarious goals.
# NOTE(clif): bare_value and value_with_spaces permit a *large* range of
# printable ASCII characters because many are used as characters with special
# meaning in several kernel parameters.
# NOTE(clif): The only permitted white-space character in this grammar is a
# space.
KERNEL_PARAMETER_GRAMMAR = r"""
kernel_command_line:  parameter_list [init_suffix]

parameter_list: parameter*(" "+ parameter)*

parameter: key
         | key_value_pair

key_value_pair: key"="value

key: /[A-Za-z0-9_\-\.]+/

value: bare_value
     | quoted_value

quoted_value: "\"" value_with_spaces "\""

bare_value: /[\!\#-\\.0-9:-\@A-Z\[-~]+/

value_with_spaces: /[\!\#-\\.0-9:-\@A-Z\[-~ ]+/

init_suffix: " "+ "--" " "+ init_arguments

init_arguments: value_with_spaces
"""

KERNEL_PARAMETER_GRAMMER_START_RULE = 'kernel_command_line'

KernelParameterParser = lark.Lark(KERNEL_PARAMETER_GRAMMAR,
                                  start=KERNEL_PARAMETER_GRAMMER_START_RULE,
                                  strict=True)


class KernelParameterTransformer(lark.Transformer):
    def kernel_command_line(self, items):
        return KernelCommandLine(items[0], items[1] or '')

    def parameter_list(self, items):
        parameters = {}
        for item in items:
            if item.key.key in parameters.keys():
                parameters[item.key.key].append(item)
            else:
                parameters[item.key.key] = [item]
        return parameters

    def parameter(self, items):
        if isinstance(items[0], ParameterKey):
            return KernelParameter(items[0], ParameterValue(""))
        return items[0]

    def key_value_pair(self, items):
        key = items[0]
        value = items[1]
        return KernelParameter(key, value)

    def key(self, items):
        return ParameterKey(items[0].value)

    def value(self, items):
        return ParameterValue(items[0])

    def quoted_value(self, items):
        return items[0]

    def bare_value(self, items):
        return items[0].value

    def value_with_spaces(self, items):
        return items[0].value

    def init_suffix(self, items):
        return items[0]

    def init_arguments(self, items):
        return items[0]
