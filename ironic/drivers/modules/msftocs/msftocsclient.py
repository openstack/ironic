# Copyright 2015 Cloudbase Solutions Srl
# All Rights Reserved.
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

"""
MSFT OCS ChassisManager v2.0 REST API client
https://github.com/MSOpenTech/ChassisManager
"""

import posixpath
from xml import etree

from oslo_log import log
import requests
from requests import auth
from requests import exceptions as requests_exceptions

from ironic.common import exception
from ironic.common.i18n import _, _LE

LOG = log.getLogger(__name__)

WCSNS = 'http://schemas.datacontract.org/2004/07/Microsoft.GFS.WCS.Contracts'
COMPLETION_CODE_SUCCESS = "Success"

BOOT_TYPE_UNKNOWN = 0
BOOT_TYPE_NO_OVERRIDE = 1
BOOT_TYPE_FORCE_PXE = 2
BOOT_TYPE_FORCE_DEFAULT_HDD = 3
BOOT_TYPE_FORCE_INTO_BIOS_SETUP = 4
BOOT_TYPE_FORCE_FLOPPY_OR_REMOVABLE = 5

BOOT_TYPE_MAP = {
    'Unknown': BOOT_TYPE_UNKNOWN,
    'NoOverride': BOOT_TYPE_NO_OVERRIDE,
    'ForcePxe': BOOT_TYPE_FORCE_PXE,
    'ForceDefaultHdd': BOOT_TYPE_FORCE_DEFAULT_HDD,
    'ForceIntoBiosSetup': BOOT_TYPE_FORCE_INTO_BIOS_SETUP,
    'ForceFloppyOrRemovable': BOOT_TYPE_FORCE_FLOPPY_OR_REMOVABLE,
}

POWER_STATUS_ON = "ON"
POWER_STATUS_OFF = "OFF"


class MSFTOCSClientApi(object):
    def __init__(self, base_url, username, password):
        self._base_url = base_url
        self._username = username
        self._password = password

    def _exec_cmd(self, rel_url):
        """Executes a command by calling the chassis manager API."""
        url = posixpath.join(self._base_url, rel_url)
        try:
            response = requests.get(
                url, auth=auth.HTTPBasicAuth(self._username, self._password))
            response.raise_for_status()
        except requests_exceptions.RequestException as ex:
            msg = _("HTTP call failed: %s") % ex
            LOG.exception(msg)
            raise exception.MSFTOCSClientApiException(msg)

        xml_response = response.text
        LOG.debug("Call to %(url)s got response: %(xml_response)s",
                  {"url": url, "xml_response": xml_response})
        return xml_response

    def _check_completion_code(self, xml_response):
        try:
            et = etree.ElementTree.fromstring(xml_response)
        except etree.ElementTree.ParseError as ex:
            LOG.exception(_LE("XML parsing failed: %s"), ex)
            raise exception.MSFTOCSClientApiException(
                _("Invalid XML: %s") % xml_response)
        item = et.find("./n:completionCode", namespaces={'n': WCSNS})
        if item is None or item.text != COMPLETION_CODE_SUCCESS:
            raise exception.MSFTOCSClientApiException(
                _("Operation failed: %s") % xml_response)
        return et

    def get_blade_state(self, blade_id):
        """Returns whether a blade's chipset is receiving power (soft-power).

        :param blade_id: the blade id
        :returns: one of:
            POWER_STATUS_ON,
            POWER_STATUS_OFF
        :raises: MSFTOCSClientApiException
        """
        et = self._check_completion_code(
            self._exec_cmd("GetBladeState?bladeId=%d" % blade_id))
        return et.find('./n:bladeState', namespaces={'n': WCSNS}).text

    def set_blade_on(self, blade_id):
        """Supplies power to a blade chipset (soft-power state).

        :param blade_id: the blade id
        :raises: MSFTOCSClientApiException
        """
        self._check_completion_code(
            self._exec_cmd("SetBladeOn?bladeId=%d" % blade_id))

    def set_blade_off(self, blade_id):
        """Shuts down a given blade (soft-power state).

        :param blade_id: the blade id
        :raises: MSFTOCSClientApiException
        """
        self._check_completion_code(
            self._exec_cmd("SetBladeOff?bladeId=%d" % blade_id))

    def set_blade_power_cycle(self, blade_id, off_time=0):
        """Performs a soft reboot of a given blade.

        :param blade_id: the blade id
        :param off_time: seconds to wait between shutdown and boot
        :raises: MSFTOCSClientApiException
        """
        self._check_completion_code(
            self._exec_cmd("SetBladeActivePowerCycle?bladeId=%(blade_id)d&"
                           "offTime=%(off_time)d" %
                           {"blade_id": blade_id, "off_time": off_time}))

    def get_next_boot(self, blade_id):
        """Returns the next boot device configured for a given blade.

        :param blade_id: the blade id
        :returns: one of:
            BOOT_TYPE_UNKNOWN,
            BOOT_TYPE_NO_OVERRIDE,
            BOOT_TYPE_FORCE_PXE, BOOT_TYPE_FORCE_DEFAULT_HDD,
            BOOT_TYPE_FORCE_INTO_BIOS_SETUP,
            BOOT_TYPE_FORCE_FLOPPY_OR_REMOVABLE
        :raises: MSFTOCSClientApiException
        """
        et = self._check_completion_code(
            self._exec_cmd("GetNextBoot?bladeId=%d" % blade_id))
        return BOOT_TYPE_MAP[
            et.find('./n:nextBoot', namespaces={'n': WCSNS}).text]

    def set_next_boot(self, blade_id, boot_type, persistent=True, uefi=True):
        """Sets the next boot device for a given blade.

        :param blade_id: the blade id
        :param boot_type: possible values:
            BOOT_TYPE_UNKNOWN,
            BOOT_TYPE_NO_OVERRIDE,
            BOOT_TYPE_FORCE_PXE,
            BOOT_TYPE_FORCE_DEFAULT_HDD,
            BOOT_TYPE_FORCE_INTO_BIOS_SETUP,
            BOOT_TYPE_FORCE_FLOPPY_OR_REMOVABLE
        :param persistent: whether this setting affects the next boot only or
            every subsequent boot
        :param uefi: True if UEFI, False otherwise
        :raises: MSFTOCSClientApiException
        """
        self._check_completion_code(
            self._exec_cmd(
                "SetNextBoot?bladeId=%(blade_id)d&bootType=%(boot_type)d&"
                "uefi=%(uefi)s&persistent=%(persistent)s" %
                {"blade_id": blade_id,
                 "boot_type": boot_type,
                 "uefi": str(uefi).lower(),
                 "persistent": str(persistent).lower()}))
