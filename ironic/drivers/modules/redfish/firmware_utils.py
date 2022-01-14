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

import jsonschema
from oslo_log import log

from ironic.common import exception
from ironic.common.i18n import _

LOG = log.getLogger(__name__)

_UPDATE_FIRMWARE_SCHEMA = {
    "$schema": "http://json-schema.org/schema#",
    "title": "update_firmware clean step schema",
    "type": "array",
    # list of firmware update images
    "items": {
        "type": "object",
        "required": ["url"],
        "properties": {
            "url": {
                "description": "URL for firmware file",
                "type": "string",
                "minLength": 1
            },
            "wait": {
                "description": "optional wait time for firmware update",
                "type": "integer",
                "minimum": 1
            }
        },
        "additionalProperties": False
    }
}


def validate_update_firmware_args(firmware_images):
    """Validate ``update_firmware`` step input argument

    :param firmware_images: args to validate.
    :raises: InvalidParameterValue When argument is not valid
    """
    try:
        jsonschema.validate(firmware_images, _UPDATE_FIRMWARE_SCHEMA)
    except jsonschema.ValidationError as err:
        raise exception.InvalidParameterValue(
            _('Invalid firmware update %(firmware_images)s. Errors: %(err)s')
            % {'firmware_images': firmware_images, 'err': err})
