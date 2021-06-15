#!/usr/bin/env python3

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

import os
import re
import sys

RELEASE_NOTES_DIR = "releasenotes/notes/"

IGNORE_FILES = (
    'releasenotes/notes/fix-get-deploy-info-port.yaml',  # Newton 6.0.0
    'releasenotes/notes/fix-mitaka-ipa-iscsi.yaml',      # Newton 6.0.0
    # Rocky, accidentally got in
    'releasenotes/notes/add-id-and-uuid-filtering-to-sqalchemy-api.yaml',
)


def main():
    return_code = 0
    for filename in os.listdir(RELEASE_NOTES_DIR):
        file_path = os.path.join(RELEASE_NOTES_DIR, filename)
        if not os.path.isfile(file_path):
            continue
        if not file_path.endswith('.yaml'):
            continue
        if file_path in IGNORE_FILES:
            continue

        if not re.search(r'.*-[0-9a-f]{16}\.yaml', file_path):
            return_code = 1
            print("Error: Release notes file: {!r} was not created with "
                  "'reno new'".format(file_path))

    return return_code


if '__main__' == __name__:
    sys.exit(main())
