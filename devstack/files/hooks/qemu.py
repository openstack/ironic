#!/usr/bin/python -tt

# Copyright (c) 2017 Intel Corporation
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
# http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import datetime
import os
import re
import sys

# This script is run as a libvirt hook.
# More information here: https://libvirt.org/hooks.html

# The devstack/lib/ironic script in function setup_qemu_log_hook() will replace
# LOG_DIR with the correct location. And will place the script into the correct
# directory.
VM_LOG_DIR = os.path.abspath("%LOG_DIR%")

# Regular expression to find ANSI escape sequences at the beginning of a string
ANSI_ESCAPE_RE = re.compile(r"""
    ^\x1b\[    # ANSI escape codes are ESC (0x1b) [
    ?([\d;]*)(\w)""", re.VERBOSE)

NOW = datetime.datetime.now().strftime("%Y-%m-%d-%H:%M:%S")


def main():
    if len(sys.argv) < 3:
        return

    guest_name = sys.argv[1]
    action = sys.argv[2]

    if action != "release":
        return

    if not console_log_exists(guest_name):
        return

    new_path = move_console_log(guest_name)
    if not new_path:
        return

    no_ansi_filename = "{}_no_ansi_{}.log".format(guest_name, NOW)
    no_ansi_path = os.path.join(VM_LOG_DIR, no_ansi_filename)
    create_no_ansi_file(new_path, no_ansi_path)


def create_no_ansi_file(source_filename, dest_filename):
    with open(source_filename) as in_file:
        data = in_file.read()

    data = remove_ansi_codes(data)

    with open(dest_filename, 'w') as out_file:
        out_file.write(data)


def get_console_log_path(guest_name):
    logfile_name = "{}_console.log".format(guest_name)
    return os.path.join(VM_LOG_DIR, logfile_name)


def console_log_exists(guest_name):
    return os.path.isfile(get_console_log_path(guest_name))


def move_console_log(guest_name):
    new_logfile_name = "{}_console_{}.log".format(guest_name, NOW)
    new_path = os.path.join(VM_LOG_DIR, new_logfile_name)
    if os.path.exists(new_path):
        return False
    os.rename(get_console_log_path(guest_name), new_path)
    return new_path


def remove_ansi_codes(data):
    """Remove any ansi codes from the provided string"""
    output = ''
    while data:
        result = ANSI_ESCAPE_RE.match(data)
        if not result:
            output += data[0]
            data = data[1:]
        else:
            data = data[result.end():]
    return output


if '__main__' == __name__:
    sys.exit(main())
