#!/usr/bin/env python3
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

import ironic.common.kernel_parameters as kp
import ironic.common.exception as exception

import argparse
import json


arg_parser = argparse.ArgumentParser(
        prog="Kernel Command Line Parser",
        description=("Validate a kernel command line or fragments to ensure "
                     "correctness by parsing it."))

arg_parser.add_argument('-p', '--print-parsed-repr',
                        action='store_true',
                        help='Print the parsed representation of the '
                             'kernel command line.')
arg_parser.add_argument('-V', '--validate-parsed-repr',
                        action='store_true',
                        help='Validate the parsed representation of '
                        'the kernel command line can be rendered back to the '
                        'original input')
arg_parser.add_argument('command_line')


RED_CODE   = 91
GREEN_CODE = 92


def format_color(content: str, color_code: int) -> str:
    return f"\033[{color_code}m{content}\033[00m"


def fail_str(content: str) -> str:
    return "[ " + format_color("FAIL", RED_CODE) + f" ]: {content}"


def pass_str(content: str) -> str:
    return "[ " + format_color("PASS", GREEN_CODE) + f" ]: {content}"


def pretty_format_kcl(kcl: kp.KernelCommandLine) -> str:
    return json.dumps(kcl.asdict(), indent=4)


def main() -> int:
    args = arg_parser.parse_args()

    try:
        kcl = kp.KernelCommandLine.parse(args.command_line)

        if args.print_parsed_repr:
            print(pretty_format_kcl(kcl))

        print(pass_str("command_line parsed successfully."))

        if args.validate_parsed_repr:
            if args.command_line == str(kcl):
                print(pass_str("Parsed command line string representation "
                               "matches original input."))
            else:
                print(fail_str("Parsed command line string representation "
                               "does NOT match original input."))
    except exception.InvalidParameterValue as e:
        print(fail_str("Kernel command line failed to parse."))
        print(e)
        return 1

    return 0

if __name__ == "__main__":
    main()
