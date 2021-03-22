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

from ironic.common.i18n import _


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
#       'api': '<Bare Metal API version>',
#       'rpc': '<RPC API version>',
#       'objects':  {
#            '<object class name>': ['<object version>'],
#       }
#    },
# }
# The list should contain all objects which are persisted in the database and
# sent over RPC. Notifications/Payloads are not being included here since we
# don't need to pin them during rolling upgrades.
#
# For each object, list the versions that the object can be in for a particular
# release. That is, any new versions that were added in that release. If there
# were no new versions, it should have the same (latest) version as the
# previous release.
# NOTE(rloo): We need a list, not just the latest version, for the DB queries
# that filter for objects that are not in particular versions; for more info,
# see comments after L1128 of
# https://review.opendev.org/#/c/408556/52/ironic/db/sqlalchemy/api.py.
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
    '9.2': {
        'rpc': '1.41',
        'api': '1.35',
        'objects': {
            'Node': ['1.21'],
            'Conductor': ['1.2'],
            'Chassis': ['1.3'],
            'Port': ['1.7'],
            'Portgroup': ['1.3'],
            'VolumeConnector': ['1.0'],
            'VolumeTarget': ['1.0'],
        }
    },
    '10.0': {
        'api': '1.36',
        'rpc': '1.42',
        'objects': {
            'Node': ['1.22'],
            'Conductor': ['1.2'],
            'Chassis': ['1.3'],
            'Port': ['1.7'],
            'Portgroup': ['1.3'],
            'VolumeConnector': ['1.0'],
            'VolumeTarget': ['1.0'],
        }
    },
    '10.1': {
        'api': '1.38',
        'rpc': '1.44',
        'objects': {
            'Node': ['1.23'],
            'Conductor': ['1.2'],
            'Chassis': ['1.3'],
            'Port': ['1.7'],
            'Portgroup': ['1.3'],
            'Trait': ['1.0'],
            'TraitList': ['1.0'],
            'VolumeConnector': ['1.0'],
            'VolumeTarget': ['1.0'],
        }
    },
    '11.0': {
        'api': '1.43',
        'rpc': '1.44',
        'objects': {
            'Node': ['1.25', '1.24'],
            'Conductor': ['1.2'],
            'Chassis': ['1.3'],
            'Port': ['1.8'],
            'Portgroup': ['1.4'],
            'Trait': ['1.0'],
            'TraitList': ['1.0'],
            'VolumeConnector': ['1.0'],
            'VolumeTarget': ['1.0'],
        }
    },
    '11.1': {
        'api': '1.46',
        'rpc': '1.47',
        'objects': {
            'Node': ['1.27', '1.26'],
            'Conductor': ['1.3'],
            'Chassis': ['1.3'],
            'Port': ['1.8'],
            'Portgroup': ['1.4'],
            'Trait': ['1.0'],
            'TraitList': ['1.0'],
            'VolumeConnector': ['1.0'],
            'VolumeTarget': ['1.0'],
        }
    },
    '12.0': {
        'api': '1.49',
        'rpc': '1.47',
        'objects': {
            'Node': ['1.29', '1.28'],
            'Conductor': ['1.3'],
            'Chassis': ['1.3'],
            'Port': ['1.8'],
            'Portgroup': ['1.4'],
            'Trait': ['1.0'],
            'TraitList': ['1.0'],
            'VolumeConnector': ['1.0'],
            'VolumeTarget': ['1.0'],
        }
    },
    '12.1': {
        'api': '1.56',
        'rpc': '1.48',
        'objects': {
            'Allocation': ['1.0'],
            'Node': ['1.32', '1.31', '1.30'],
            'Conductor': ['1.3'],
            'Chassis': ['1.3'],
            'DeployTemplate': ['1.0', '1.1'],
            'Port': ['1.9'],
            'Portgroup': ['1.4'],
            'Trait': ['1.0'],
            'TraitList': ['1.0'],
            'VolumeConnector': ['1.0'],
            'VolumeTarget': ['1.0'],
        }
    },
    '12.2': {
        'api': '1.58',
        'rpc': '1.48',
        'objects': {
            'Allocation': ['1.0'],
            'Node': ['1.32'],
            'Conductor': ['1.3'],
            'Chassis': ['1.3'],
            'DeployTemplate': ['1.1'],
            'Port': ['1.9'],
            'Portgroup': ['1.4'],
            'Trait': ['1.0'],
            'TraitList': ['1.0'],
            'VolumeConnector': ['1.0'],
            'VolumeTarget': ['1.0'],
        }
    },
    '13.0': {
        'api': '1.58',
        'rpc': '1.48',
        'objects': {
            'Allocation': ['1.0'],
            'Node': ['1.32'],
            'Conductor': ['1.3'],
            'Chassis': ['1.3'],
            'DeployTemplate': ['1.1'],
            'Port': ['1.9'],
            'Portgroup': ['1.4'],
            'Trait': ['1.0'],
            'TraitList': ['1.0'],
            'VolumeConnector': ['1.0'],
            'VolumeTarget': ['1.0'],
        }
    },
    '14.0': {
        'api': '1.61',
        'rpc': '1.48',
        'objects': {
            'Allocation': ['1.1'],
            'Node': ['1.33', '1.32'],
            'Conductor': ['1.3'],
            'Chassis': ['1.3'],
            'DeployTemplate': ['1.1'],
            'Port': ['1.9'],
            'Portgroup': ['1.4'],
            'Trait': ['1.0'],
            'TraitList': ['1.0'],
            'VolumeConnector': ['1.0'],
            'VolumeTarget': ['1.0'],
        }
    },
    '15.0': {
        'api': '1.65',
        'rpc': '1.50',
        'objects': {
            'Allocation': ['1.1'],
            'Node': ['1.34', '1.33', '1.32'],
            'Conductor': ['1.3'],
            'Chassis': ['1.3'],
            'DeployTemplate': ['1.1'],
            'Port': ['1.9'],
            'Portgroup': ['1.4'],
            'Trait': ['1.0'],
            'TraitList': ['1.0'],
            'VolumeConnector': ['1.0'],
            'VolumeTarget': ['1.0'],
        }
    },
    '15.1': {
        'api': '1.67',
        'rpc': '1.50',
        'objects': {
            'Allocation': ['1.1'],
            'Node': ['1.35', '1.34'],
            'Conductor': ['1.3'],
            'Chassis': ['1.3'],
            'DeployTemplate': ['1.1'],
            'Port': ['1.9'],
            'Portgroup': ['1.4'],
            'Trait': ['1.0'],
            'TraitList': ['1.0'],
            'VolumeConnector': ['1.0'],
            'VolumeTarget': ['1.0'],
        }
    },
    '16.0': {
        'api': '1.68',
        'rpc': '1.51',
        'objects': {
            'Allocation': ['1.1'],
            'Node': ['1.35'],
            'Conductor': ['1.3'],
            'Chassis': ['1.3'],
            'Deployment': ['1.0'],
            'DeployTemplate': ['1.1'],
            'Port': ['1.9'],
            'Portgroup': ['1.4'],
            'Trait': ['1.0'],
            'TraitList': ['1.0'],
            'VolumeConnector': ['1.0'],
            'VolumeTarget': ['1.0'],
        }
    },
    '16.1': {
        'api': '1.68',
        'rpc': '1.51',
        'objects': {
            'Allocation': ['1.1'],
            'Node': ['1.35'],
            'Conductor': ['1.3'],
            'Chassis': ['1.3'],
            'Deployment': ['1.0'],
            'DeployTemplate': ['1.1'],
            'Port': ['1.9'],
            'Portgroup': ['1.4'],
            'Trait': ['1.0'],
            'TraitList': ['1.0'],
            'VolumeConnector': ['1.0'],
            'VolumeTarget': ['1.0'],
        }
    },
    '16.2': {
        'api': '1.69',
        'rpc': '1.52',
        'objects': {
            'Allocation': ['1.1'],
            'Node': ['1.35'],
            'Conductor': ['1.3'],
            'Chassis': ['1.3'],
            'Deployment': ['1.0'],
            'DeployTemplate': ['1.1'],
            'Port': ['1.10'],
            'Portgroup': ['1.4'],
            'Trait': ['1.0'],
            'TraitList': ['1.0'],
            'VolumeConnector': ['1.0'],
            'VolumeTarget': ['1.0'],
        }
    },
    '17.0': {
        'api': '1.71',
        'rpc': '1.53',
        'objects': {
            'Allocation': ['1.1'],
            'Node': ['1.35'],
            'Conductor': ['1.3'],
            'Chassis': ['1.3'],
            'Deployment': ['1.0'],
            'DeployTemplate': ['1.1'],
            'Port': ['1.10'],
            'Portgroup': ['1.4'],
            'Trait': ['1.0'],
            'TraitList': ['1.0'],
            'VolumeConnector': ['1.0'],
            'VolumeTarget': ['1.0'],
        }
    },
    'master': {
        'api': '1.71',
        'rpc': '1.53',
        'objects': {
            'Allocation': ['1.1'],
            'Node': ['1.35'],
            'Conductor': ['1.3'],
            'Chassis': ['1.3'],
            'Deployment': ['1.0'],
            'DeployTemplate': ['1.1'],
            'Port': ['1.10'],
            'Portgroup': ['1.4'],
            'Trait': ['1.0'],
            'TraitList': ['1.0'],
            'VolumeConnector': ['1.0'],
            'VolumeTarget': ['1.0'],
        }
    },
}

# NOTE(xek): Assign each named release to the appropriate semver.
#
#            Just before we do a new named release (more specifically, create
#            a stable/<release> branch), add a mapping for the new named
#            release. This is needed; otherwise CI: a unit test (common.
#            ReleaseMappingsTestCase.test_contains_current_release_entry())
#            and grenade that tests old/new (new-release -> master) will fail.
#
#            Just after we do a new named release, delete the oldest named
#            release (that we are no longer supporting for a rolling upgrade).
#
#            There should be at most two named mappings here.

# NOTE(mgoddard): remove victoria prior to the xena release.
RELEASE_MAPPING['victoria'] = RELEASE_MAPPING['16.0']
RELEASE_MAPPING['wallaby'] = RELEASE_MAPPING['17.0']

# List of available versions with named versions first; 'master' is excluded.
RELEASE_VERSIONS = sorted(set(RELEASE_MAPPING) - {'master'}, reverse=True)

# List of available (version, description) tuples.
RELEASE_VERSIONS_DESCS = [(v, _('"%s" release') % v) for v in RELEASE_VERSIONS]


def get_object_versions(releases=None, objects=None):
    """Gets the supported versions for all objects.

    Supported versions are from the RELEASE_MAPPINGs.

    :param releases: a list of release names; if empty/None, versions from all
                     releases are returned (the default).
    :param objects: a list of names of objects of interest. If empty/None,
                    versions of all objects are returned (the default).

    :returns: a dictionary where the key is the object name and the value is
              a set of supported versions.
    """
    if not releases:
        releases = list(RELEASE_MAPPING)

    versions = {}
    for release in releases:
        object_mapping = RELEASE_MAPPING[release]['objects']
        for obj, version_list in object_mapping.items():
            if not objects or obj in objects:
                versions.setdefault(obj, set()).update(version_list)

    return versions
