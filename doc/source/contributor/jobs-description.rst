.. _jobs-description:

================
Jobs description
================

The description of each jobs that runs in the CI when you submit a patch for
`openstack/ironic` is visible in :ref:`table_jobs_description`.

.. _table_jobs_description:

.. list-table:: Table. OpenStack Ironic CI jobs description
   :widths: 53 47
   :header-rows: 1

   * - Job name
     - Description
   * - ironic-tox-unit-with-driver-libs-python3
     - Runs Ironic unit tests with the driver dependencies installed under
       Python3
   * - ironic-standalone
     - Deploys Ironic in standalone mode and runs tempest tests that match
       the regex `ironic_standalone`.
   * - ironic-tempest-functional-python3
     - Deploys Ironic in standalone mode and runs tempest functional tests
       that matches the regex `ironic_tempest_plugin.tests.api` under Python3
   * - ironic-grenade
     - Deploys Ironic in a DevStack and runs upgrade for all enabled services.
   * - ironic-grenade-dsvm-multinode-multitenant
     - Deploys Ironic in a multinode DevStack and runs upgrade for all enabled
       services.
   * - ironic-tempest-ipa-partition-pxe_ipmitool
     - Deploys Ironic in DevStack under Python3, configured to use dib
       ramdisk partition image with `pxe` boot and `ipmi` driver.
       Runs tempest tests that match the regex
       `ironic_tempest_plugin.tests.scenario` and deploy 1 virtual baremetal.
   * - ironic-tempest-partition-bios-redfish-pxe
     - Deploys Ironic in DevStack, configured to use dib ramdisk partition
       image with `pxe` boot and `redfish` driver.
       Runs tempest tests that match the regex
       `ironic_tempest_plugin.tests.scenario`, also deploys 1 virtual
       baremetal.
   * - ironic-tempest-ipa-partition-uefi-pxe_ipmitool
     - Deploys Ironic in DevStack, configured to use dib ramdisk partition
       image with `uefi` boot and `ipmi` driver.
       Runs tempest tests that match the regex
       `ironic_tempest_plugin.tests.scenario`, also deploys 1 virtual
       baremetal.
   * - ironic-tempest-ipa-wholedisk-direct-tinyipa-multinode
     - Deploys Ironic in a multinode DevStack, configured to use a pre-build
       tinyipa ramdisk wholedisk image that is downloaded from a Swift
       temporary url, `pxe` boot and `ipmi` driver.
       Runs tempest tests that match the regex
       `(ironic_tempest_plugin.tests.scenario|test_schedule_to_all_nodes)`
       and deploys 7 virtual baremetal.
   * - ironic-tempest-ipa-wholedisk-bios-agent_ipmitool-tinyipa
     - Deploys Ironic in DevStack, configured to use a pre-build tinyipa
       ramdisk wholedisk image that is downloaded from a Swift temporary url,
       `pxe` boot and `ipmi` driver.
       Runs tempest tests that match the regex
       `ironic_tempest_plugin.tests.scenario` and deploys 1 virtual baremetal.
   * - ironic-tempest-ipa-wholedisk-bios-agent_ipmitool-indirect
     - Deploys Ironic in DevStack, configured to use a pre-built dib
       ramdisk wholedisk image that is downloaded from http url, `pxe` boot
       and `ipmi` driver.
       Runs tempest tests that match the regex
       `ironic_tempest_plugin.tests.scenario` and deploys 1 virtual baremetal.
   * - ironic-tempest-ipa-partition-bios-agent_ipmitool-indirect
     - Deploys Ironic in DevStack, configured to use a pre-built dib
       ramdisk partition image that is downloaded from http url, `pxe` boot
       and `ipmi` driver.
       Runs tempest tests that match the regex
       `ironic_tempest_plugin.tests.scenario` and deploys 1 virtual baremetal.
   * - ironic-tempest-bfv
     - Deploys Ironic in DevStack with cinder enabled, so it can deploy
       baremetal using boot from volume.
       Runs tempest tests that match the regex `baremetal_boot_from_volume`
       and deploys 3 virtual baremetal nodes using boot from volume.
   * - ironic-tempest-ipa-partition-uefi-pxe-grub2
     - Deploys Ironic in DevStack, configured to use pxe with uefi and grub2
       and `ipmi` driver.
       Runs tempest tests that match the regex
       `ironic_tempest_plugin.tests.scenario` and deploys 1 virtual baremetal.
   * - ironic-tox-bandit
     - Runs bandit security tests in a tox environment to find known issues in
       the Ironic code.
   * - ironic-tempest-ipa-wholedisk-bios-pxe_snmp
     - Deploys Ironic in DevStack, configured to use a pre-built dib
       ramdisk wholedisk image that is downloaded from a Swift temporary url,
       `pxe` boot and `snmp` driver.
       Runs tempest tests that match the regex
       `ironic_tempest_plugin.tests.scenario` and deploys 1 virtual baremetal.
   * - ironic-inspector-tempest
     - Deploys Ironic and Ironic Inspector in DevStack, configured to use a
       pre-build tinyipa ramdisk wholedisk image that is downloaded from a
       Swift temporary url, `pxe` boot and `ipmi` driver.
       Runs tempest tests that match the regex `InspectorBasicTest` and
       deploys 1 virtual baremetal.
   * - bifrost-integration-tinyipa-ubuntu-bionic
     - Tests the integration between Ironic and Bifrost.
   * - metalsmith-integration-glance-localboot-centos7
     - Tests the integration between Ironic and Metalsmith using Glance as
       image source and CentOS7 with local boot.
   * - ironic-tempest-pxe_ipmitool-postgres
     - Deploys Ironic in DevStack, configured to use tinyipa ramdisk partition
       image with `pxe` boot and `ipmi` driver and postgres instead of mysql.
       Runs tempest tests that match the regex
       `ironic_tempest_plugin.tests.scenario`, also deploys 1 virtual
       baremetal.
