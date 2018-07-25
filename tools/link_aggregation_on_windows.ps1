#ps1_sysnative

# Copyright 2018 FUJITSU LIMITED
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

# Load network_data.json
$dir_data_config_file = (Get-ChildItem -Path ($PSCommandPath | Split-Path -Parent) -Filter 'network_data.json' -File -Recurse).fullname
$network_data = Get-Content -Raw -Path $dir_data_config_file | ConvertFrom-Json

# Create NIC Teaming base on netwok_data.json
$MAC_MASTER=''
foreach ($nic in $network_data.links)
{
    if ($nic.type -like 'bond')
    {
        $nic_master=Get-NetAdapter | where MacAddress -eq $nic.ethernet_mac_address.Replace(':','-').ToUpper()
        $MAC_MASTER = $nic.ethernet_mac_address.Replace(':','-').ToUpper()
        New-NetLbfoTeam -Name 'openstack' -TeamMembers $nic_master.Name -TeamingMode SwitchIndependent -LoadBalancingAlgorithm MacAddresses -Confirm:$false
    }
    if ($nic.type -like 'phy')
    {
        $MAC_MEMBER = $nic.ethernet_mac_address.Replace(':','-').ToUpper()
        if($MAC_MEMBER -notlike $MAC_MASTER)
        {
            $nic_member=Get-NetAdapter | where MacAddress -eq $MAC_MEMBER
            Add-NetLbfoTeamMember -Name $nic_member.Name -Team 'openstack' -Confirm:$false
        }
    }
}
