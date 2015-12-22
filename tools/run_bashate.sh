#!/bin/bash
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

find  "$@"  -not \( -type d -name .?\* -prune \)    \
            -type f                                 \
            -not -name \*.swp                       \
            -not -name \*~                          \
            -not -name \*.xml                       \
            -not -name \*.template                  \
            -not -name \*.py                        \
            \(                                      \
                -name \*.sh -or                     \
                -wholename \*/lib/\* -or            \
                -wholename \*/tools/\*              \
            \)                                      \
            -print0 | xargs -0 bashate -v -iE006 -eE005,E042
