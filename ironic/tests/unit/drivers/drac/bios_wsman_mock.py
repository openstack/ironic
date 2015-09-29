#
# Copyright 2015 Dell, Inc.
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
Test class for DRAC BIOS interface
"""

from ironic.drivers.modules.drac import resource_uris

Enumerations = {
    resource_uris.DCIM_BIOSEnumeration: {
        'XML': """<ns0:Envelope
xmlns:ns0="http://www.w3.org/2003/05/soap-envelope"
xmlns:ns1="http://schemas.xmlsoap.org/ws/2004/08/addressing"
xmlns:ns2="http://schemas.xmlsoap.org/ws/2004/09/enumeration"
xmlns:ns3="http://schemas.dmtf.org/wbem/wsman/1/wsman.xsd"
xmlns:ns4="http://schemas.dell.com/wbem/wscim/1/cim-schema/2/DCIM_BIOSEnumeration"
xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">
  <ns0:Header>
    <ns1:To>http://schemas.xmlsoap.org/ws/2004/08/addressing/role/anonymous
</ns1:To>
    <ns1:Action>
http://schemas.xmlsoap.org/ws/2004/09/enumeration/EnumerateResponse</ns1:Action>
    <ns1:RelatesTo>uuid:1f5cd907-0e6f-1e6f-8002-4f266e3acab8</ns1:RelatesTo>
    <ns1:MessageID>uuid:219ca357-0e6f-1e6f-a828-f0e4fb722ab8</ns1:MessageID>
  </ns0:Header>
  <ns0:Body>
    <ns2:EnumerateResponse>
      <ns3:Items>
        <ns4:DCIM_BIOSEnumeration>
          <ns4:AttributeName>MemTest</ns4:AttributeName>
          <ns4:CurrentValue>Disabled</ns4:CurrentValue>
          <ns4:Dependency xsi:nil="true" />
          <ns4:DisplayOrder>310</ns4:DisplayOrder>
          <ns4:FQDD>BIOS.Setup.1-1</ns4:FQDD>
          <ns4:GroupDisplayName>Memory Settings</ns4:GroupDisplayName>
          <ns4:GroupID>MemSettings</ns4:GroupID>
          <ns4:InstanceID>BIOS.Setup.1-1:MemTest</ns4:InstanceID>
          <ns4:IsReadOnly>false</ns4:IsReadOnly>
          <ns4:PendingValue xsi:nil="true" />
          <ns4:PossibleValues>Enabled</ns4:PossibleValues>
          <ns4:PossibleValues>Disabled</ns4:PossibleValues>
        </ns4:DCIM_BIOSEnumeration>
        <ns4:DCIM_BIOSEnumeration>
          <ns4:AttributeDisplayName>C States</ns4:AttributeDisplayName>
          <ns4:AttributeName>ProcCStates</ns4:AttributeName>
          <ns4:CurrentValue>Disabled</ns4:CurrentValue>
          <ns4:DisplayOrder>1706</ns4:DisplayOrder>
          <ns4:FQDD>BIOS.Setup.1-1</ns4:FQDD>
          <ns4:GroupDisplayName>System Profile Settings</ns4:GroupDisplayName>
          <ns4:GroupID>SysProfileSettings</ns4:GroupID>
          <ns4:InstanceID>BIOS.Setup.1-1:ProcCStates</ns4:InstanceID>
          <ns4:IsReadOnly>true</ns4:IsReadOnly>
          <ns4:PendingValue xsi:nil="true" />
          <ns4:PossibleValues>Enabled</ns4:PossibleValues>
          <ns4:PossibleValues>Disabled</ns4:PossibleValues>
        </ns4:DCIM_BIOSEnumeration>
       </ns3:Items>
    </ns2:EnumerateResponse>
  </ns0:Body>
        </ns0:Envelope>""",
        'Dict': {
            'MemTest': {
                'name': 'MemTest',
                'current_value': 'Disabled',
                'pending_value': None,
                'read_only': False,
                'possible_values': ['Disabled', 'Enabled']},
            'ProcCStates': {
                'name': 'ProcCStates',
                'current_value': 'Disabled',
                'pending_value': None,
                'read_only': True,
                'possible_values': ['Disabled', 'Enabled']}}},
    resource_uris.DCIM_BIOSString: {
        'XML': """<ns0:Envelope
xmlns:ns0="http://www.w3.org/2003/05/soap-envelope"
xmlns:ns1="http://schemas.xmlsoap.org/ws/2004/08/addressing"
xmlns:ns2="http://schemas.xmlsoap.org/ws/2004/09/enumeration"
xmlns:ns3="http://schemas.dmtf.org/wbem/wsman/1/wsman.xsd"
xmlns:ns4="http://schemas.dell.com/wbem/wscim/1/cim-schema/2/DCIM_BIOSString"
xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">
  <ns0:Header>
    <ns1:To>http://schemas.xmlsoap.org/ws/2004/08/addressing/role/anonymous
</ns1:To>
    <ns1:Action>
http://schemas.xmlsoap.org/ws/2004/09/enumeration/EnumerateResponse
</ns1:Action>
    <ns1:RelatesTo>uuid:1f877bcb-0e6f-1e6f-8004-4f266e3acab8</ns1:RelatesTo>
    <ns1:MessageID>uuid:21bea321-0e6f-1e6f-a82b-f0e4fb722ab8</ns1:MessageID>
  </ns0:Header>
  <ns0:Body>
    <ns2:EnumerateResponse>
      <ns3:Items>
        <ns4:DCIM_BIOSString>
          <ns4:AttributeName>SystemModelName</ns4:AttributeName>
          <ns4:CurrentValue>PowerEdge R630</ns4:CurrentValue>
          <ns4:Dependency xsi:nil="true" />
          <ns4:DisplayOrder>201</ns4:DisplayOrder>
          <ns4:FQDD>BIOS.Setup.1-1</ns4:FQDD>
          <ns4:GroupDisplayName>System Information</ns4:GroupDisplayName>
          <ns4:GroupID>SysInformation</ns4:GroupID>
          <ns4:InstanceID>BIOS.Setup.1-1:SystemModelName</ns4:InstanceID>
          <ns4:IsReadOnly>true</ns4:IsReadOnly>
          <ns4:MaxLength>40</ns4:MaxLength>
          <ns4:MinLength>0</ns4:MinLength>
          <ns4:PendingValue xsi:nil="true" />
          <ns4:ValueExpression xsi:nil="true" />
        </ns4:DCIM_BIOSString>
        <ns4:DCIM_BIOSString>
          <ns4:AttributeName>SystemModelName2</ns4:AttributeName>
          <ns4:CurrentValue>PowerEdge R630</ns4:CurrentValue>
          <ns4:Dependency xsi:nil="true" />
          <ns4:DisplayOrder>201</ns4:DisplayOrder>
          <ns4:FQDD>BIOS.Setup.1-1</ns4:FQDD>
          <ns4:GroupDisplayName>System Information</ns4:GroupDisplayName>
          <ns4:GroupID>SysInformation</ns4:GroupID>
          <ns4:InstanceID>BIOS.Setup.1-1:SystemModelName2</ns4:InstanceID>
          <ns4:IsReadOnly>true</ns4:IsReadOnly>
          <ns4:MaxLength>40</ns4:MaxLength>
          <ns4:MinLength>0</ns4:MinLength>
          <ns4:PendingValue xsi:nil="true" />
        </ns4:DCIM_BIOSString>
        <ns4:DCIM_BIOSString>
          <ns4:AttributeDisplayName>Asset Tag</ns4:AttributeDisplayName>
          <ns4:AttributeName>AssetTag</ns4:AttributeName>
          <ns4:CurrentValue xsi:nil="true" />
          <ns4:Dependency xsi:nil="true" />
          <ns4:DisplayOrder>1903</ns4:DisplayOrder>
          <ns4:FQDD>BIOS.Setup.1-1</ns4:FQDD>
          <ns4:GroupDisplayName>Miscellaneous Settings</ns4:GroupDisplayName>
          <ns4:GroupID>MiscSettings</ns4:GroupID>
          <ns4:InstanceID>BIOS.Setup.1-1:AssetTag</ns4:InstanceID>
          <ns4:IsReadOnly>false</ns4:IsReadOnly>
          <ns4:MaxLength>63</ns4:MaxLength>
          <ns4:MinLength>0</ns4:MinLength>
          <ns4:PendingValue xsi:nil="true" />
          <ns4:ValueExpression>^[ -~]{0,63}$</ns4:ValueExpression>
        </ns4:DCIM_BIOSString>
       </ns3:Items>
      <ns2:EnumerationContext />
      <ns3:EndOfSequence />
    </ns2:EnumerateResponse>
  </ns0:Body>
        </ns0:Envelope>""",
        'Dict': {
            'SystemModelName': {
                'name': 'SystemModelName',
                'current_value': 'PowerEdge R630',
                'pending_value': None,
                'read_only': True,
                'min_length': 0,
                'max_length': 40,
                'pcre_regex': None},
            'SystemModelName2': {
                'name': 'SystemModelName2',
                'current_value': 'PowerEdge R630',
                'pending_value': None,
                'read_only': True,
                'min_length': 0,
                'max_length': 40,
                'pcre_regex': None},
            'AssetTag': {
                'name': 'AssetTag',
                'current_value': None,
                'pending_value': None,
                'read_only': False,
                'min_length': 0,
                'max_length': 63,
                'pcre_regex': '^[ -~]{0,63}$'}}},
    resource_uris.DCIM_BIOSInteger: {
        'XML': """<ns0:Envelope
xmlns:ns0="http://www.w3.org/2003/05/soap-envelope"
xmlns:ns1="http://schemas.xmlsoap.org/ws/2004/08/addressing"
xmlns:ns2="http://schemas.xmlsoap.org/ws/2004/09/enumeration"
xmlns:ns3="http://schemas.dmtf.org/wbem/wsman/1/wsman.xsd"
xmlns:ns4="http://schemas.dell.com/wbem/wscim/1/cim-schema/2/DCIM_BIOSInteger"
xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">
  <ns0:Header>
    <ns1:To>
http://schemas.xmlsoap.org/ws/2004/08/addressing/role/anonymous</ns1:To>
    <ns1:Action>
http://schemas.xmlsoap.org/ws/2004/09/enumeration/EnumerateResponse</ns1:Action>
    <ns1:RelatesTo>uuid:1fa60792-0e6f-1e6f-8005-4f266e3acab8</ns1:RelatesTo>
    <ns1:MessageID>uuid:21ccf01d-0e6f-1e6f-a82d-f0e4fb722ab8</ns1:MessageID>
  </ns0:Header>
  <ns0:Body>
    <ns2:EnumerateResponse>
      <ns3:Items>
        <ns4:DCIM_BIOSInteger>
          <ns4:AttributeName>Proc1NumCores</ns4:AttributeName>
          <ns4:CurrentValue>8</ns4:CurrentValue>
          <ns4:Dependency xsi:nil="true" />
          <ns4:DisplayOrder>439</ns4:DisplayOrder>
          <ns4:FQDD>BIOS.Setup.1-1</ns4:FQDD>
          <ns4:GroupDisplayName>Processor Settings</ns4:GroupDisplayName>
          <ns4:GroupID>ProcSettings</ns4:GroupID>
          <ns4:InstanceID>BIOS.Setup.1-1:Proc1NumCores</ns4:InstanceID>
          <ns4:IsReadOnly>true</ns4:IsReadOnly>
          <ns4:LowerBound>0</ns4:LowerBound>
          <ns4:PendingValue xsi:nil="true" />
          <ns4:UpperBound>65535</ns4:UpperBound>
        </ns4:DCIM_BIOSInteger>
        <ns4:DCIM_BIOSInteger>
          <ns4:AttributeName>AcPwrRcvryUserDelay</ns4:AttributeName>
          <ns4:CurrentValue>60</ns4:CurrentValue>
          <ns4:DisplayOrder>1825</ns4:DisplayOrder>
          <ns4:FQDD>BIOS.Setup.1-1</ns4:FQDD>
          <ns4:GroupDisplayName>System Security</ns4:GroupDisplayName>
          <ns4:GroupID>SysSecurity</ns4:GroupID>
          <ns4:InstanceID>BIOS.Setup.1-1:AcPwrRcvryUserDelay</ns4:InstanceID>
          <ns4:IsReadOnly>false</ns4:IsReadOnly>
          <ns4:LowerBound>60</ns4:LowerBound>
          <ns4:PendingValue xsi:nil="true" />
          <ns4:UpperBound>240</ns4:UpperBound>
        </ns4:DCIM_BIOSInteger>
      </ns3:Items>
      <ns2:EnumerationContext />
      <ns3:EndOfSequence />
    </ns2:EnumerateResponse>
  </ns0:Body>
        </ns0:Envelope>""",
        'Dict': {
            'Proc1NumCores': {
                'name': 'Proc1NumCores',
                'current_value': 8,
                'pending_value': None,
                'read_only': True,
                'lower_bound': 0,
                'upper_bound': 65535},
            'AcPwrRcvryUserDelay': {
                'name': 'AcPwrRcvryUserDelay',
                'current_value': 60,
                'pending_value': None,
                'read_only': False,
                'lower_bound': 60,
                'upper_bound': 240}}}}

Invoke_Commit = """<ns0:Envelope
xmlns:ns0="http://www.w3.org/2003/05/soap-envelope"
xmlns:ns1="http://schemas.xmlsoap.org/ws/2004/08/addressing"
xmlns:ns2="http://schemas.dell.com/wbem/wscim/1/cim-schema/2/DCIM_BIOSService">
  <ns0:Header>
    <ns1:To>
http://schemas.xmlsoap.org/ws/2004/08/addressing/role/anonymous</ns1:To>
    <ns1:Action>
http://schemas.dell.com/wbem/wscim/1/cim-schema/2/DCIM_BIOSService/SetAttributesResponse</ns1:Action>
    <ns1:RelatesTo>uuid:42baa476-0ee9-1ee9-8020-4f266e3acab8</ns1:RelatesTo>
    <ns1:MessageID>uuid:fadae2f8-0eea-1eea-9626-76a8f1d9bed4</ns1:MessageID>
  </ns0:Header>
  <ns0:Body>
    <ns2:SetAttributes_OUTPUT>
      <ns2:Message>The command was successful.</ns2:Message>
      <ns2:MessageID>BIOS001</ns2:MessageID>
      <ns2:RebootRequired>Yes</ns2:RebootRequired>
      <ns2:ReturnValue>0</ns2:ReturnValue>
      <ns2:SetResult>Set PendingValue</ns2:SetResult>
    </ns2:SetAttributes_OUTPUT>
  </ns0:Body>
</ns0:Envelope>"""
