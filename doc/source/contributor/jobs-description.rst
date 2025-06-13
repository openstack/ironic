.. _jobs-description:

================
Jobs description
================

The description of each jobs that runs in the CI when you submit a patch for
``openstack/ironic`` is visible in :ref:`table_jobs_description`.

.. note:: Ironic CI jobs are now documented using the "description" field
          in the job definition that they are created in.

.. _table_jobs_description:

.. list-table:: Table. OpenStack Ironic CI jobs description
  :widths: 53 47
  :header-rows: 1

  * - Job name
    - Description
  * - bifrost-integration-tinyipa-ubuntu-focal
    - Tests the integration between Ironic and Bifrost using a tinyipa image.
  * - bifrost-integration-redfish-vmedia-uefi-centos-9
    - Tests the integration between Ironic and Bifrost using redfish vmedia and
      a dib image based on centos stream 9.
  * - `metal3-integration`_
    - Tests the integration between Ironic and `Metal3`_ using the
      `metal3-dev-env`_ environment

.. _metal3-integration: metal3-integration.html
.. _Metal3: https://metal3.io/
.. _metal3-dev-env: https://github.com/metal3-io/metal3-dev-env
