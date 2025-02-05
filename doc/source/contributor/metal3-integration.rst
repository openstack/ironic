.. _metal3-integration:

=============================
Metal3 Continuous Integration
=============================

The Metal3 Continuous Integration job, named ``metal3-integration`` in the zuul
configuration file, deploys a kubernetes cluster on emulated bare metal nodes,
helping tests the ironic source code using the `Metal3 Development
Environment (metal3-dev-env)`_ workflow from the `Metal3`_ project.

=================
Job configuration
=================

While the `metal3-integration job definition yaml file`_ is in the same path
of the other Ironic CI jobs, it uses separate configuration files under
`playbooks/metal3-ci`_ in the Ironic repository.
The configuration follows ansible syntax as for other CI jobs.
The actual job is configured in `run.yaml`_, where various environment variables
for metal3-dev-env are defined under the ``metal3_environment`` entry.
For more info about the metal3-dev-env environment variables definition and
values please see the `metal3-dev-env env variables`_ page.
In `post.yaml`_ we execute some post execution operations, like collecting logs
and environment configuration, that are useful in case of troubleshooting.

====================================
Metal3 Development Environment Guide
====================================

To familiarize with the `Metal3 Development Environment (metal3-dev-env)`_,
the Metal3 workflow, and in general with the project, it's recommended to
follow the `TryIt`_ section of the Metal3 User Guide.
The metal3-dev-env workflow steps are explained in Section 1.2.

The `Metal3 Development Environment (metal3-dev-env)`_ is maintained by the
`Metal3`_ project community which is present in the ``#cluster-api-baremetal``
channel on Kubernetes Slack.
For any questions or help on the project, or to escalate issues related to the
``metal3-integration`` job please contact the Metal3 community.

=====================
Troubleshooting Guide
=====================

The ``metal3-integration`` job logs are stored in the same way and
following roughly the same path of the other Ironic CI jobs.
In the main directory the ``job-output.txt`` file contains the console
output of the job and, if any failure exists, the main reason of the breakage.
Other useful logs are stored under the ``controller`` directory:

* ``before_pivoting`` directory stores services logs of the management cluster

* ``libvirt`` directory stores libvirt configuration and logs, including
  console logs of the emulated bare metal nodes

* ``management_cluster`` directory stores all configuration and logs of the
  metal3 services, such as the baremetal-operator (BMO)

* ``system`` directory stores information and logs from the operating system
  where metal3-dev-env is running


.. _Metal3 Development Environment (metal3-dev-env): https://github.com/metal3-io/metal3-dev-env
.. _Metal3: https://metal3.io/
.. _metal3-integration job definition yaml file: https://opendev.org/openstack/ironic/src/branch/master/zuul.d/metal3-jobs.yaml
.. _playbooks/metal3-ci: https://opendev.org/openstack/ironic/src/branch/master/playbooks/metal3-ci
.. _run.yaml: https://opendev.org/openstack/ironic/src/branch/master/playbooks/metal3-ci/run.yaml
.. _metal3-dev-env env variables: https://github.com/metal3-io/metal3-dev-env/blob/main/vars.md
.. _post.yaml: https://opendev.org/openstack/ironic/src/branch/master/playbooks/metal3-ci/post.yaml
.. _TryIt: https://book.metal3.io/developer_environment/tryit
.. _Bare Metal Operator: https://github.com/metal3-io/baremetal-operator
