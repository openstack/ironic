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

from dataclasses import dataclass
from typing import Dict
from typing import List

from ironic.common.exception import InvalidParameterValue
from ironic.common.i18n import _
from ironic.common.kernel_parameter_parser.kernel_parameter_parser \
    import Lark_StandAlone
from ironic.common.kernel_parameter_parser.kernel_parameter_parser \
    import LarkError
from ironic.common.kernel_parameter_parser.kernel_parameter_parser \
    import Transformer
from ironic.common.kernel_parameter_parser.kernel_parameter_parser \
    import UnexpectedInput


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


KernelParameterParser = Lark_StandAlone(debug=True)


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
            return f"{self.key.key}={self.value.value}"
        return self.key.key


_INIT_ARG_PREAMBLE = " -- "


# NOTE(clif): We're handling init args here instead of inside the grammar
# because Lark's stand-alone LALR(1) parser can't handle it.
def _divide_command_line_by_init_args(command_line):
    index = command_line.rfind(_INIT_ARG_PREAMBLE)
    if index == -1:
        return (command_line, '')
    return (command_line[:index],
            command_line[index + len(_INIT_ARG_PREAMBLE):])


@dataclass(frozen=True)
class KernelCommandLine:
    parameters: Dict[str, List[KernelParameter]]
    init_args: str

    def __str__(self):
        output = ' '.join(
            ' '.join(str(param) for param in param_list)
            for param_list in self.parameters.values())
        if len(self.init_args) > 0:
            output += _INIT_ARG_PREAMBLE + self.init_args
        return output

    @classmethod
    def parse(cls, command_line: str):
        try:
            cmd_line, init_args = \
                _divide_command_line_by_init_args(command_line)
            tree = KernelParameterParser.parse(cmd_line)
            kcl = KernelParameterTransformer().transform(tree)
            return KernelCommandLine(kcl.parameters, init_args)
        except (LarkError, UnexpectedInput) as e:
            raise InvalidParameterValue(
                _('Kernel command line did not parse: "%s" -- %s')
                % (command_line, str(e))) from None


class KernelParameterTransformer(Transformer):
    def kernel_command_line(self, items):
        # NOTE(clif) adding init arguments to the grammar is too much for
        # Lark's stand-alone LALR(1) parser. Therefore it isn't part of the
        # back-ported grammar.
        return KernelCommandLine(items[0], '')

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
        # Strip " characters from literal.
        return items[0].value[1:-1]

    def bare_value(self, items):
        return items[0].value

    def value_with_spaces(self, items):
        return items[0].value

    def init_suffix(self, items):
        return items[0]

    def init_arguments(self, items):
        return items[0]
