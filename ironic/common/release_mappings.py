#    Copyright 2016 Intel Corp.
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

# NOTE(xek): This decides the version cap of RPC messages sent to conductor
# and objects during rolling upgrades, when [DEFAULT]/pin_release_version
# configuration is set.
#
# Remember to add a new entry for the new version that is shipping in a new
# release.
#
# We support a rolling upgrade between adjacent named releases, as well as
# between a release and master, so old, unsupported releases can be removed,
# together with the supporting code, which is typically found in an object's
# make_compatible methods and RPC client code.

# NOTE(xek): The format of this dict is:
# { '<release version>': {
#       'rpc': '<RPC API version>',
#       'objects':  {
#            '<object class name>': '<object version>',
#       }
#    },
# }
# The list should contain all objects which are persisted in the database and
# sent over RPC. Notifications/Payloads are not being included here since we
# don't need to pin them during rolling upgrades.
#
# There should always be a 'master' entry that reflects the objects in the
# master branch.
#
# Just before doing a release, copy the 'master' entry, and rename the first
# 'master' entry to the (semver) version being released.
#
# Just after doing a named release, delete any entries associated with the
# oldest named release.
RELEASE_MAPPING = {
    '7.0': {
        'rpc': '1.40',
        'objects': {
            'Node': '1.21',
            'Conductor': '1.2',
            'Chassis': '1.3',
            'Port': '1.6',
            'Portgroup': '1.3',
            'VolumeConnector': '1.0',
            'VolumeTarget': '1.0',
        }
    },
    '8.0': {
        'rpc': '1.40',
        'objects': {
            'Node': '1.21',
            'Conductor': '1.2',
            'Chassis': '1.3',
            'Port': '1.6',
            'Portgroup': '1.3',
            'VolumeConnector': '1.0',
            'VolumeTarget': '1.0',
        }
    },
    'master': {
        'rpc': '1.40',
        'objects': {
            'Node': '1.21',
            'Conductor': '1.2',
            'Chassis': '1.3',
            'Port': '1.7',
            'Portgroup': '1.3',
            'VolumeConnector': '1.0',
            'VolumeTarget': '1.0',
        }
    },
}

# NOTE(xek): Assign each named release to the appropriate semver.
#
#            Just before we do a new named release, add a mapping for the new
#            named release.
#
#            Just after we do a new named release, delete the oldest named
#            release (that we are no longer supporting for a rolling upgrade).
#
#            There should be at most two named mappings here.
RELEASE_MAPPING['ocata'] = RELEASE_MAPPING['7.0']

# List of available versions with named versions first; 'master' is excluded.
RELEASE_VERSIONS = sorted(set(RELEASE_MAPPING) - {'master'}, reverse=True)
