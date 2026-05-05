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

from ironic.common.exception import InvalidParameterValue
import ironic.common.kernel_parameters as kp
from ironic.tests import base

from ddt import data
from ddt import ddt
from ddt import unpack
import lark


def annotate(name, *args):
    class AnnotatedList(list):
        pass

    al = AnnotatedList([*args])
    al.__name__ = name
    return al


def generate_invalid_characters_to_test():
    invalid_characters_to_test = [
        chr(c) for c in range(0, 32)
    ]
    invalid_characters_to_test.extend([
        "\n",
        "\r",
        chr(127),
    ])
    invalid_characters_to_test.extend([
        chr(c) for c in range(128, 160)
    ])
    return invalid_characters_to_test


INVALID_CHARACTERS = generate_invalid_characters_to_test()


@ddt
class KernelParametersTestCase(base.TestCase):
    @data(
        annotate(
            "Filtering newlines",
            "quiet\n",
            "quiet"
        ),
        annotate(
            "Filtering carraige returns",
            "qu\riet",
            "quiet"
        ),
        annotate(
            "Filtering NULL",
            "\0quiet",
            "quiet"
        ),
        annotate(
            "Nothing needs changing - a real valid kernel cmdline",
            ("BOOT_IMAGE=(hd5,gpt2)/vmlinuz-6.19.9-200.fc43.x86_64 "
             "root=UUID=217c8a40-4956-11f1-9c98-d8bbc1c85452 ro "
             "rootflags=subvol=root "
             "rd.luks.uuid=luks-3a516752-4956-11f1-aa13-d8bbc1c85452 "
             "rhgb quiet rd.driver.blacklist=nouveau,nova_core "
             "modprobe.blacklist=nouveau,nova_core"),
            ("BOOT_IMAGE=(hd5,gpt2)/vmlinuz-6.19.9-200.fc43.x86_64 "
             "root=UUID=217c8a40-4956-11f1-9c98-d8bbc1c85452 ro "
             "rootflags=subvol=root "
             "rd.luks.uuid=luks-3a516752-4956-11f1-aa13-d8bbc1c85452 "
             "rhgb quiet rd.driver.blacklist=nouveau,nova_core "
             "modprobe.blacklist=nouveau,nova_core")
        ),
    )
    @unpack
    def test_sanitize_kernel_command_line(
            self, command_line: str, expected_result: str):
        self.assertEqual(
            expected_result,
            kp.sanitize_kernel_command_line(command_line))

    def test_grammar_acceptable_to_lark(self):
        parser = lark.Lark(
            kp.KERNEL_PARAMETER_GRAMMAR,
            start=kp.KERNEL_PARAMETER_GRAMMER_START_RULE)
        self.assertIsNotNone(parser)

    @data(
        annotate(
            "Single key=value pair",
            "BOOT_IMAGE=(hd5,gpt2)/vmlinuz-6.19.9-200.fc43.x86_64",
            kp.KernelCommandLine({
                'BOOT_IMAGE': [kp.KernelParameter(
                    kp.ParameterKey('BOOT_IMAGE'),
                    kp.ParameterValue(
                        '(hd5,gpt2)/vmlinuz-6.19.9-200.fc43.x86_64')
                )],
            }, "")
        ),
        annotate(
            "Single key",
            "quiet",
            kp.KernelCommandLine({
                'quiet': [kp.KernelParameter(
                    kp.ParameterKey('quiet'),
                    kp.ParameterValue(''),
                )],
            }, "")
        ),
        annotate(
            "Two parameters",
            "quiet BOOT_IMAGE=(hd5,gpt2)/vmlinuz-6.19.9-200.fc43.x86_64",
            kp.KernelCommandLine({
                'quiet': [kp.KernelParameter(
                    kp.ParameterKey('quiet'),
                    kp.ParameterValue(''),
                )],
                'BOOT_IMAGE': [kp.KernelParameter(
                    kp.ParameterKey('BOOT_IMAGE'),
                    kp.ParameterValue(
                        '(hd5,gpt2)/vmlinuz-6.19.9-200.fc43.x86_64')
                )],
            }, "")
        ),
        annotate(
            "A real linux kernel cmdline",
            ("BOOT_IMAGE=(hd5,gpt2)/vmlinuz-6.19.9-200.fc43.x86_64 "
             "root=UUID=217c8a40-4956-11f1-9c98-d8bbc1c85452 ro "
             "rootflags=subvol=root "
             "rd.luks.uuid=luks-3a516752-4956-11f1-aa13-d8bbc1c85452 "
             "rhgb quiet rd.driver.blacklist=nouveau,nova_core "
             "modprobe.blacklist=nouveau,nova_core"),
            kp.KernelCommandLine({
                'BOOT_IMAGE': [kp.KernelParameter(
                    kp.ParameterKey('BOOT_IMAGE'),
                    kp.ParameterValue(
                        '(hd5,gpt2)/vmlinuz-6.19.9-200.fc43.x86_64')
                )],
                'root': [kp.KernelParameter(
                    kp.ParameterKey('root'),
                    kp.ParameterValue(
                        'UUID=217c8a40-4956-11f1-9c98-d8bbc1c85452'),
                )],
                'ro': [kp.KernelParameter(
                    kp.ParameterKey('ro'),
                    kp.ParameterValue(''),
                )],
                'rootflags': [kp.KernelParameter(
                    kp.ParameterKey('rootflags'),
                    kp.ParameterValue('subvol=root'),
                )],
                'rd.luks.uuid': [kp.KernelParameter(
                    kp.ParameterKey('rd.luks.uuid'),
                    kp.ParameterValue(
                        'luks-3a516752-4956-11f1-aa13-d8bbc1c85452'),
                )],
                'rhgb': [kp.KernelParameter(
                    kp.ParameterKey('rhgb'),
                    kp.ParameterValue(''),
                )],
                'quiet': [kp.KernelParameter(
                    kp.ParameterKey('quiet'),
                    kp.ParameterValue(''),
                )],
                'rd.driver.blacklist': [kp.KernelParameter(
                    kp.ParameterKey('rd.driver.blacklist'),
                    kp.ParameterValue('nouveau,nova_core'),
                )],
                'modprobe.blacklist': [kp.KernelParameter(
                    kp.ParameterKey('modprobe.blacklist'),
                    kp.ParameterValue('nouveau,nova_core'),
                )],
            }, "")
        ),
        annotate(
            "Multiple parameters with the same key",
            "initrd=/initramfs-linux.img initrd=ramdisk",
            kp.KernelCommandLine({
                'initrd': [kp.KernelParameter(
                    kp.ParameterKey('initrd'),
                    kp.ParameterValue('/initramfs-linux.img')
                 ),
                 kp.KernelParameter(
                    kp.ParameterKey('initrd'),
                    kp.ParameterValue('ramdisk')
                 )]
            }, "")
        ),
        annotate(
            "init arguments",
            "quiet -- some init args",
            kp.KernelCommandLine({
                'quiet': [kp.KernelParameter(
                    kp.ParameterKey('quiet'),
                    kp.ParameterValue(''),
                )],
            }, "some init args")
        ),
    )
    @unpack
    def test_kernel_command_line_parsing(
            self, command_line: str, expected_result: kp.KernelCommandLine):
        result = kp.KernelCommandLine.parse(command_line)
        # Assert parsing the command line spits out the expected
        # object.
        self.assertEqual(expected_result, result)
        # Assert rendering the object back to a string matches the initial
        # command line string.
        self.assertEqual(command_line, str(result))

    @data(
        *[annotate(
                f"character ordinal {ord(c)} shouldn't parse",
                f"ro{c}quiet",) for c in INVALID_CHARACTERS]
    )
    @unpack
    def test_invalid_kernel_command_lines_fail_to_parse(
            self, command_line: str):
        with self.assertRaises(InvalidParameterValue):
            kp.KernelCommandLine.parse(command_line)
