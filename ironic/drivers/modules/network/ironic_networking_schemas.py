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

"""
JSON Schema definitions for the ironic-networking network interface.

This module contains the JSON schemas used to validate switchport and LAG
configuration in port and portgroup 'extra' fields.
"""

SWITCHPORT_SCHEMA = {
    "$schema": "http://json-schema.org/draft-04/schema#",
    "title": "Ironic Networking Network Interface Switchport Configuration "
             "Schema",
    "description": "Schema for validating switchport configuration in port "
                   "'extra' field for ironic networking network interface. "
                   "Switch ID and port name are obtained from "
                   "local_link_connection, and description is generated "
                   "automatically.",
    "type": "object",
    "properties": {
        "mode": {
            "type": "string",
            "description": "Switch port mode configuration",
            "enum": ["access", "trunk", "hybrid"]
        },
        "native_vlan": {
            "type": "integer",
            "description": "Native VLAN ID for the port",
            "minimum": 1,
            "maximum": 4094
        },
        "allowed_vlans": {
            "type": "array",
            "description": "List of allowed VLAN IDs for trunk/hybrid modes",
            "items": {
                "type": "integer",
                "minimum": 1,
                "maximum": 4094
            },
            "uniqueItems": True,
            "maxItems": 100
        },
        "lag_name": {
            "type": "string",
            "description": "Name of the LAG this port belongs to",
            "maxLength": 255
        },
        "mtu": {
            "type": "integer",
            "description": "Ethernet Maximum Transmission Unit of the port",
            "maximum": 9216
        }
    },
    "required": ["mode", "native_vlan"],
    "additionalProperties": False,
    "allOf": [
        {
            "if": {
                "properties": {
                    "mode": {"const": "access"}
                }
            },
            "then": {
                "not": {
                    "required": ["allowed_vlans"]
                }
            }
        },
        {
            "if": {
                "properties": {
                    "mode": {"enum": ["trunk", "hybrid"]}
                }
            },
            "then": {
                "properties": {
                    "allowed_vlans": {
                        "minItems": 1
                    }
                },
                "required": ["allowed_vlans"]
            }
        }
    ]
}

LAG_SCHEMA = {
    "$schema": "http://json-schema.org/draft-04/schema#",
    "title": "Ironic Networking Network Interface LAG Configuration Schema",
    "description": "Schema for validating LAG configuration in portgroup "
                   "'extra' field for ironic networking network interface. "
                   "Different modes have different requirements for VLAN "
                   "configuration.",
    "type": "object",
    "properties": {
        "mode": {
            "type": "string",
            "description": "LAG mode configuration",
            "enum": ["access", "trunk", "hybrid"]
        },
        "native_vlan": {
            "type": "integer",
            "description": "The native VLAN ID for the LAG. If not supplied "
                           "then the switch global default VLAN ID is used.",
            "minimum": 1,
            "maximum": 4094
        },
        "allowed_vlans": {
            "type": "array",
            "description": "List of allowed VLAN IDs for trunk mode",
            "items": {
                "type": "integer",
                "minimum": 1,
                "maximum": 4094
            },
            "uniqueItems": True,
            "maxItems": 100
        },
        "aggregation_mode": {
            "type": "string",
            "description": "Link aggregation protocol mode",
            "enum": ["lacp", "static"]
        },
        "mtu": {
            "type": "integer",
            "description": "Ethernet Maximum Transmission Unit of the port",
            "maximum": 9216
        }
    },
    "required": ["mode", "aggregation_mode"],
    "additionalProperties": False,
    "allOf": [
        {
            "if": {
                "properties": {
                    "mode": {"const": "access"}
                }
            },
            "then": {
                "not": {
                    "required": ["allowed_vlans"]
                }
            }
        },
        {
            "if": {
                "properties": {
                    "mode": {"enum": ["trunk", "hybrid"]}
                }
            },
            "then": {
                "properties": {
                    "allowed_vlans": {
                        "minItems": 1
                    }
                },
                "required": ["allowed_vlans"]
            }
        }
    ]
}
