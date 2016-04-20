# Copyright 2014 Hewlett-Packard Development Company, L.P.
#
# Licensed under the Apache License, Version 2.0 (the "License"); you may
# not use this file except in compliance with the License. You may obtain
# a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
# WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
# License for the specific language governing permissions and limitations
# under the License.

# Different RAID configurations for unit tests in test_raid.py

RAID_CONFIG_OKAY = '''
{
  "logical_disks": [
      {
       "raid_level": "1",
       "size_gb": 100,
       "volume_name": "my-volume",
       "is_root_volume": true,
       "share_physical_disks": false,
       "disk_type": "ssd",
       "interface_type": "sas",
       "number_of_physical_disks": 2,
       "controller": "Smart Array P822 in Slot 2",
       "physical_disks": [
                          "5I:1:1",
                          "5I:1:2"
                         ]
      }
  ]
}
'''

RAID_CONFIG_NO_LOGICAL_DISKS = '''
{
  "logical_disks": []
}
'''

RAID_CONFIG_NO_RAID_LEVEL = '''
{
  "logical_disks": [
      {
       "size_gb": 100
      }
  ]
}
'''

RAID_CONFIG_INVALID_RAID_LEVEL = '''
{
  "logical_disks": [
      {
       "size_gb": 100,
       "raid_level": "foo"
      }
  ]
}
'''

RAID_CONFIG_NO_SIZE_GB = '''
{
  "logical_disks": [
      {
       "raid_level": "1"
      }
  ]
}
'''

RAID_CONFIG_INVALID_SIZE_GB = '''
{
  "logical_disks": [
      {
       "raid_level": "1",
       "size_gb": "abcd"
      }
  ]
}
'''

RAID_CONFIG_MAX_SIZE_GB = '''
{
  "logical_disks": [
      {
       "raid_level": "1",
       "size_gb": "MAX"
      }
  ]
}
'''

RAID_CONFIG_INVALID_IS_ROOT_VOL = '''
{
  "logical_disks": [
      {
       "raid_level": "1",
       "size_gb": 100,
       "is_root_volume": "True"
      }
  ]
}
'''

RAID_CONFIG_MULTIPLE_IS_ROOT_VOL = '''
{
  "logical_disks": [
      {
       "raid_level": "1",
       "size_gb": 100,
       "is_root_volume": true
      },
      {
       "raid_level": "1",
       "size_gb": 100,
       "is_root_volume": true
      }
  ]
}
'''

RAID_CONFIG_INVALID_SHARE_PHY_DISKS = '''
{
  "logical_disks": [
      {
       "raid_level": "1",
       "size_gb": 100,
       "share_physical_disks": "True"
      }
  ]
}
'''

RAID_CONFIG_INVALID_DISK_TYPE = '''
{
  "logical_disks": [
      {
       "raid_level": "1",
       "size_gb": 100,
       "disk_type": "foo"
      }
  ]
}
'''

RAID_CONFIG_INVALID_INT_TYPE = '''
{
  "logical_disks": [
      {
       "raid_level": "1",
       "size_gb": 100,
       "interface_type": "foo"
      }
  ]
}
'''

RAID_CONFIG_INVALID_NUM_PHY_DISKS = '''
{
  "logical_disks": [
      {
       "raid_level": "1",
       "size_gb": 100,
       "number_of_physical_disks": "a"
      }
  ]
}
'''

RAID_CONFIG_INVALID_PHY_DISKS = '''
{
  "logical_disks": [
      {
       "raid_level": "1",
       "size_gb": 100,
       "controller": "Smart Array P822 in Slot 2",
       "physical_disks": "5I:1:1"
      }
  ]
}
'''

RAID_CONFIG_ADDITIONAL_PROP = '''
{
  "logical_disks": [
      {
       "raid_levelllllll": "1",
       "size_gb": 100
      }
  ]
}
'''

RAID_CONFIG_JBOD_VOLUME = '''
{
  "logical_disks": [
      {
       "raid_level": "JBOD",
       "size_gb": 100
      }
  ]
}
'''

CUSTOM_SCHEMA_RAID_CONFIG = '''
{
  "logical_disks": [
      {
       "raid_level": "1",
       "size_gb": 100,
       "foo": "bar"
      }
  ]
}
'''

CUSTOM_RAID_SCHEMA = '''
{
    "type": "object",
    "properties": {
        "logical_disks": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "raid_level": {
                        "type": "string",
                        "enum": [ "0", "1", "2", "5", "6", "1+0" ],
                        "description": "RAID level for the logical disk."
                    },
                    "size_gb": {
                        "type": "integer",
                        "minimum": 0,
                        "exclusiveMinimum": true,
                        "description": "Size (Integer) for the logical disk."
                    },
                    "foo": {
                        "type": "string",
                        "description": "property foo"
                    }
                },
                "required": ["raid_level", "size_gb"],
                "additionalProperties": false
            },
            "minItems": 1
        }
    },
    "required": ["logical_disks"],
    "additionalProperties": false
}
'''

CURRENT_RAID_CONFIG = '''
{
  "logical_disks": [
      {
       "raid_level": "1",
       "size_gb": 100,
       "controller": "Smart Array P822 in Slot 2",
       "is_root_volume": true,
       "physical_disks": [
                          "5I:1:1",
                          "5I:1:2"
                         ],
       "root_device_hint": {
           "wwn": "600508B100"
       }
      }
  ]
}
'''

RAID_CONFIG_MULTIPLE_ROOT = '''
{
  "logical_disks": [
      {
       "raid_level": "1",
       "size_gb": 100,
       "controller": "Smart Array P822 in Slot 2",
       "is_root_volume": true,
       "physical_disks": [
                          "5I:1:1",
                          "5I:1:2"
                         ],
       "root_device_hint": {
           "wwn": "600508B100"
       }
      },
      {
       "raid_level": "1",
       "size_gb": 100,
       "controller": "Smart Array P822 in Slot 2",
       "is_root_volume": true,
       "physical_disks": [
                          "5I:1:1",
                          "5I:1:2"
                         ],
       "root_device_hint": {
           "wwn": "600508B100"
       }
      }
  ]
}
'''
