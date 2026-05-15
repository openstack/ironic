.. _metal3-integration:

=============================
Metal3 Continuous Integration
=============================

There are three jobs that use Metal3_ project to test Ironic:

- `Metal3 Integration Job`_ tests the entire Metal3 flow from creating a
  cluster with *Cluster API* to provisioning nodes.

- `Ironic Standalone Operator Functional Tests`_ check how Ironic is installed
  in Metal3.

- `Bare Metal Operator Functional Tests`_ check various scenarios of using
  Ironic through Metal3 API.

Metal3 Integration Job
======================

The Metal3 Continuous Integration job, named ``metal3-integration`` in the zuul
configuration file, deploys a kubernetes cluster on emulated bare metal nodes,
helping tests the ironic source code using the `Metal3 Development
Environment (metal3-dev-env)`_ workflow from the `Metal3`_ project.

Job configuration
-----------------

While the `metal3 job definition yaml file`_ is in the same path
of the other Ironic CI jobs, it uses separate configuration files under
`playbooks/metal3-ci`_ in the Ironic repository.
The configuration follows ansible syntax as for other CI jobs.
The actual job is configured in `run.yaml`_, where various environment variables
for metal3-dev-env are defined under the ``metal3_environment`` entry.
For more info about the metal3-dev-env environment variables definition and
values please see the `metal3-dev-env env variables`_ page.
In `post.yaml`_ we execute some post execution operations, like collecting logs
and environment configuration, that are useful in case of troubleshooting.

Metal3 Development Environment Guide
------------------------------------

To familiarize with the `Metal3 Development Environment (metal3-dev-env)`_,
the Metal3 workflow, and in general with the project, it's recommended to
follow the `TryIt`_ section of the Metal3 User Guide.
The metal3-dev-env workflow steps are explained in Section 1.2.

The `Metal3 Development Environment (metal3-dev-env)`_ is maintained by the
`Metal3`_ project community which is present in the ``#cluster-api-baremetal``
channel on Kubernetes Slack.
For any questions or help on the project, or to escalate issues related to the
``metal3-integration`` job please contact the Metal3 community.

Troubleshooting Guide
---------------------

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

Ironic Standalone Operator Functional Tests
===========================================

`Ironic Standalone Operator`_ (IrSO) is a Kubernetes operator that installs and
manages Ironic in a configuration suitable for Metal3. It uses ironic-image_
provided by Metal3 behind the scenes.

The job does not use metal3-dev-env. Instead, the scripts are shared between
two Metal3 repositories:

- `hack/prepare-irso-tests.sh`_ in ironic-image builds a custom container image
  with the Ironic source from Zuul.
- `test/prepare.sh`_ in IrSO configures the testing cluster and installs
  dependencies.
- `test/run.sh`_ in IrSO runs the test suite.

How It Works
------------

The tests are running against a compact Kubernetes cluster built with
Minikube_, where IrSO itself, cert-manager and MariaDB are installed during the
preparation phase. A separate namespace is created for each test, and all tests
are executed sequentially.

Tests start by creating an `Ironic resource`_ with a certain configuration and
verifying that its reconciliation succeeds (or fails as expected). Then Ironic
API itself is tested by creating and deleting 100 nodes. In some cases, the
resource is updated and the corresponding change is observed in the Ironic
deployment. Check the `IrSO testing guide`_ for more details how tests are
written.

The job running on Ironic has two peculiarities:

- Upgrade tests are not run because of using a custom Ironic image.
- A single-node Minikube clusters is used for all tests. HA tests do run still
  but in a single replica mode.

Troubleshooting Guide
---------------------

Typical causes of failures include:

- Bugs that prevent start-up of Ironic in a certain configuration
- Bugs that prevent enrolling nodes
- Issues with SQLite support
- Issues with JSON RPC, including severe performance problems
- Issues with Ironic Prometheus Exporter or Ironic Networking integration
- Transient failures when building the image (Quay, GitHub or CentOS Stream
  mirrors availability)

Since this job does not exercise any provisioning processes, failures are not
caused by bugs in them.

Logs Layout
~~~~~~~~~~~

In the end of a test run, a jUnit report is rendered and published in the job
artifacts. There you can see which tests have failed and also its namespace,
which is the first label listed in square brackets.

The logs inside ``controller`` root are organized as follows:

- ``controller/pod/`` contains the IrSO logs. They are shared for all test
  runs, so look for the namespace of interest.
- ``system/`` contains various system resources: processes, firewall rules, etc.
- ``test-<namespace>/`` contains resources from each test run:

  - ``ironic_test-ironic.yaml`` is the definition of the Ironic resource.
    Check it to see what configuration was requested.
  - ``deployment_test-ironic-service.yaml`` is the resulting Kubernetes
    Deployment object. Check it to see what configuration is actually applied.
  - ``pod_test-ironic-service-<random>/`` contains logs from all pods from the
    resulting deployment. If the Ironic resource is changed, there will be
    several of these, each corresponding to a state before or after the change.

  .. note:: The repeated ``test-ironic`` bit is the name of the Ironic
            resource, that is used in all tests.

Bare Metal Operator Functional Tests
====================================

`Bare Metal Operator`_ (BMO) is the core component of Metal3. It exposes
several Kubernetes resources for managing hardware, using Ironic as its
backend.

The job does not use metal3-dev-env. Instead, the scripts are shared between
two Metal3 repositories:

- `hack/prepare-bmo-tests.sh`_ script in ironic-image_ builds a custom
  container image with the Ironic source from Zuul, and runs the next script:
- `hack/ci-e2e.sh`_ in BMO installs dependencies, configures networking,
  installs the BMC emulator (sushy-tools_ in case of the job running on
  Ironic), creates a testing image, and runs the test suite.

How It Works
------------

The test suite itself is responsible for the rest of the configuration. It
creates a Kind_ cluster, installs `Ironic Standalone Operator`_, installs
Ironic using the operator and the previously built Ironic image, and deploys
BMO itself.

After the bootstrapping phase, all tests are run in two threads, each
corresponding to one of the two fake bare-metal machines. Tests normally
involve creating a BareMetalHost resource with its BMC credentials secret and
observing it walking through expected states_.

Each group of tests run in their own namespace.

Troubleshooting Guide
---------------------

Typical causes of failures that are not caused by BMO itself include:

- Bugs in any major provisioning process: enrollment, inspection, manual
  cleaning, deployment, automated cleaning, or servicing (but not rescuing).
- Bugs in the ramdisk deploy feature or virtual media support.
- Bugs in general standalone Ironic support (e.g. basic auth).
- Transient failures when building the image (Quay, GitHub or CentOS Stream
  mirrors availability).

Logs Layout
~~~~~~~~~~~

In the end of a test run, a jUnit report is rendered and published in the job
artifacts. There you can see which tests have failed.

The logs inside ``controller`` root are organized as follows:

- ``system/`` contains various system resources: processes, firewall rules, etc.
- ``logs/baremetal-operator-system/baremetal-operator-controller-manager/``
  contains BMO logs shared between all tests.
- ``logs/baremetal-operator-system/ironic-service/`` contains logs from all
  Ironic services.
- ``logs/qemu/`` contains QEMU logs and serial console output from testing VMs.
- ``resources/`` contains Kubernetes events per each testing namespace.
- the remaining directories contain resources from each testing namespace:

  - ``crd/`` contains Kubernetes resources in YAML format. Particularly of
    interest are *BareMetalHosts* (correspond to Ironic nodes and their ports),
    *HostFirmwareSettings* (correspond to BIOS settings),
    *HostFirmwareComponents* (correspond to firmware operations) and
    *HardwareData* (stores inspection inventory).
  - ``bmo-e2e-<index>-serial0.log`` serial console output for corresponding
    VM(s).

- ``redfish-emulator.log`` contains sushy-tools_ logs.

.. _Metal3: https://metal3.io/
.. _Metal3 Development Environment (metal3-dev-env): https://github.com/metal3-io/metal3-dev-env
.. _metal3 job definition yaml file: https://opendev.org/openstack/ironic/src/branch/master/zuul.d/metal3-jobs.yaml
.. _playbooks/metal3-ci: https://opendev.org/openstack/ironic/src/branch/master/playbooks/metal3-ci
.. _run.yaml: https://opendev.org/openstack/ironic/src/branch/master/playbooks/metal3-ci/run.yaml
.. _metal3-dev-env env variables: https://github.com/metal3-io/metal3-dev-env/blob/main/vars.md
.. _post.yaml: https://opendev.org/openstack/ironic/src/branch/master/playbooks/metal3-ci/post.yaml
.. _TryIt: https://book.metal3.io/developer_environment/tryit
.. _Bare Metal Operator: https://github.com/metal3-io/baremetal-operator
.. _Ironic Standalone Operator: https://github.com/metal3-io/ironic-standalone-operator
.. _ironic-image: https://github.com/metal3-io/ironic-image/
.. _hack/prepare-irso-tests.sh: https://github.com/metal3-io/ironic-image/blob/main/hack/prepare-irso-tests.sh
.. _test/prepare.sh: https://github.com/metal3-io/ironic-standalone-operator/blob/main/test/prepare.sh
.. _test/run.sh: https://github.com/metal3-io/ironic-standalone-operator/blob/main/test/run.sh
.. _minikube: https://minikube.sigs.k8s.io/docs/
.. _Ironic resource: https://github.com/metal3-io/ironic-standalone-operator/blob/main/docs/api.md#ironic
.. _IrSO testing guide: https://github.com/metal3-io/ironic-standalone-operator/blob/main/docs/testing.md#functional-tests
.. _hack/prepare-bmo-tests.sh: https://github.com/metal3-io/ironic-image/blob/main/hack/prepare-bmo-tests.sh
.. _hack/ci-e2e.sh: https://github.com/metal3-io/baremetal-operator/blob/main/hack/ci-e2e.sh
.. _Kind: https://kind.sigs.k8s.io/
.. _sushy-tools: https://opendev.org/openstack/sushy-tools/
.. _states: https://book.metal3.io/bmo/state_machine.html
