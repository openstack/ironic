.. meta::
   :description: Running OCI containers as steps on bare metal
       nodes using Ironic runbooks and the IPA Container Hardware Manager.
   :keywords: container cleaning, podman, OCI, runbooks, IPA,
       ironic-python-agent, automated cleaning
   :author: OpenStack Ironic Team
   :robots: index, follow
   :audience: system administrators, operators

.. _container-based-steps:

=====================
Container-Based Steps
=====================

Overview
========

The Container Hardware Manager in ironic-python-agent (IPA) allows running
OCI-compatible containers as steps on bare metal nodes. This enables
operators to package arbitrary tools -- firmware updaters, diagnostic suites,
compliance scanners -- as container images and execute them during any
step-based workflow, such as cleaning, deployment, or servicing.

Basics
======

A workflow for implementing container-based steps with runbooks is:

1. The operator builds an IPA ramdisk with the ``ironic-python-agent-podman``
   diskimage-builder element, which installs podman and the Container Hardware
   Manager into the ramdisk.

2. The Ironic conductor sends ``[agent_containers]`` configuration to IPA
   via the lookup/heartbeat endpoint. This allows conductor-side settings
   to override any build-time defaults in the ramdisk.

3. When a runbook triggers a ``generic_container_step``, IPA uses podman (or
   docker) to pull and run the specified container image on the bare metal
   node.

4. The container runs with host networking by default, executes its task,
   and exits. IPA reports the result back to the conductor.

Prerequisites
=============

IPA ramdisk with podman support
-------------------------------

The IPA ramdisk must be built with the ``ironic-python-agent-podman``
diskimage-builder (DIB) element. This element is currently **Debian-based
only**.

.. code-block:: bash

    export DIB_ALLOW_ARBITRARY_CONTAINERS=true
    export DIB_RUNNER=podman

    disk-image-create ironic-python-agent-ramdisk \
        ironic-python-agent-podman \
        debian -o ipa-with-podman

Key DIB environment variables:

``DIB_ALLOW_ARBITRARY_CONTAINERS``
    Set to ``true`` to allow any container image. Set to ``false`` (default)
    to restrict to a specific allowlist. Environments which permit non-admin
    roles to create and execute runbooks should not set this to ``true`` for
    security reasons.

``DIB_ALLOWED_CONTAINERS``
    Comma-separated list of allowed container image URLs. Only used when
    ``DIB_ALLOW_ARBITRARY_CONTAINERS`` is ``false``.

``DIB_RUNNER``
    Container runtime: ``podman`` (default) or ``docker``.

Container registry access
-------------------------

The container registry hosting your images must be accessible from the
cleaning network. If using a private registry, ensure credentials and TLS
certificates are configured in the ramdisk or passed via
``pull_options``.

Ironic Conductor Configuration
==============================

The ``[agent_containers]`` configuration group controls how the conductor
instructs IPA to handle containers. These settings are sent to IPA at
lookup time, so changes take effect without rebuilding the ramdisk.

.. code-block:: ini

    [agent_containers]
    # Allow any container image (default: false)
    allow_arbitrary_containers = false

    # Allowlist of container images (used when above is false)
    allowed_containers = docker://registry.example.com/firmware-tool:latest,docker://registry.example.com/diag-suite:v2

    # Container runtime (default: podman)
    runner = podman

    # Options passed to the pull command (comma separated list)
    pull_options = --tls-verify=false

    # Options passed to the run command (comma separated list)
    run_options = --rm,--network=host,--tls-verify=false

.. important::
   ``pull_options`` and ``run_options`` are **comma** separated lists, not
   space separated strings. ``--rm --network=host`` is a single option
   containing spaces, which the container runtime will reject.

.. warning::
   Setting ``allow_arbitrary_containers = true`` allows **any** container
   image to be pulled and executed with host-level network access on the
   bare metal node. Only enable this in trusted environments. Prefer using
   ``allowed_containers`` to maintain an explicit allowlist.

See also:
:oslo.config:option:`agent_containers.allow_arbitrary_containers`,
:oslo.config:option:`agent_containers.allowed_containers`,
:oslo.config:option:`agent_containers.runner`,
:oslo.config:option:`agent_containers.pull_options`,
:oslo.config:option:`agent_containers.run_options`.

Example Container-based Runbooks
================================

The built-in step
-----------------

The Container Hardware Manager exposes a built-in step called
``generic_container_step`` on the ``deploy`` interface. This step has a
default priority of ``0``, meaning it only runs when explicitly invoked
via manual cleaning, servicing, or a runbook.

.. note::
   This step was previously called ``container_clean_step``. That name is
   deprecated but still works, so existing runbooks keep functioning; it
   will be removed in a future release. The step serves cleaning, deployment
   and servicing alike, which is why the name no longer says "clean".

The step accepts the following arguments:

``container_url`` (required)
    The full container image URL, e.g.
    ``docker://registry.example.com/firmware-tool:latest``. Unless
    ``allow_arbitrary_containers`` is enabled, this must appear in
    ``allowed_containers``.

``pull_options`` (optional)
    Override the default pull options for this specific container. Ignored
    when ``allow_arbitrary_containers`` is ``false``. See
    `Security Considerations`_.

``run_options`` (optional)
    Override the default run options for this specific container. Ignored
    when ``allow_arbitrary_containers`` is ``false``. See
    `Security Considerations`_.

Single-container runbook
------------------------

This example creates a runbook that runs a single firmware update
container:

.. code-block:: bash

    baremetal runbook create \
        --name CUSTOM_CONTAINER_FW_UPDATE \
        --steps '[
            {
                "interface": "deploy",
                "step": "generic_container_step",
                "args": {
                    "container_url": "docker://registry.example.com/firmware-tool:latest"
                },
                "order": 1
            }
        ]'

Multi-container runbook
-----------------------

Runbooks can combine multiple container steps with traditional steps.
This example runs a diagnostic container, then a firmware updater,
and finishes with a standard disk metadata erase:

.. code-block:: bash

    baremetal runbook create \
        --name CUSTOM_CONTAINER_CLEAN \
        --steps '[
            {
                "interface": "deploy",
                "step": "generic_container_step",
                "args": {
                    "container_url": "docker://registry.example.com/diag-suite:v2"
                },
                "order": 1
            },
            {
                "interface": "deploy",
                "step": "generic_container_step",
                "args": {
                    "container_url": "docker://registry.example.com/firmware-tool:latest",
                    "run_options": ["--rm", "--network=host", "--privileged"]
                },
                "order": 2
            },
            {
                "interface": "deploy",
                "step": "erase_devices_metadata",
                "args": {},
                "order": 3
            }
        ]'

.. note::
   The ``run_options`` in the second step above only take effect when
   ``allow_arbitrary_containers`` is ``true``. In the default locked down
   configuration the conductor's configured ``run_options`` are used
   instead, because options such as ``--privileged`` would otherwise let a
   runbook escape the ``allowed_containers`` allowlist entirely.

Adding traits to nodes
----------------------

Runbooks are matched to nodes via traits. Add the matching trait to all
nodes that should use the runbook::

    baremetal node add trait <node> CUSTOM_CONTAINER_CLEAN

Using the Runbook
=================

Manual cleaning
---------------

Trigger the runbook on a node in ``manageable`` state:

.. code-block:: bash

    baremetal node clean <node> --runbook CUSTOM_CONTAINER_CLEAN

Automated cleaning
------------------

To use container-based steps for automated cleaning, configure the
conductor to use runbook-based or hybrid cleaning and assign the runbook.
See :ref:`runbook-cleaning` for full details on the available
configuration levels (per-node, per-resource-class, global).

A minimal example using the global default:

.. code-block:: ini

    [conductor]
    automated_clean = true
    automated_cleaning_step_source = runbook
    automated_cleaning_runbook = CUSTOM_CONTAINER_CLEAN

All nodes must have the matching trait (``CUSTOM_CONTAINER_CLEAN``) unless
trait validation is disabled via
:oslo.config:option:`conductor.automated_cleaning_runbook_validate_traits`.

Servicing
---------

Container steps also work with :ref:`servicing`. Trigger a container
runbook on an ``active`` node:

.. code-block:: bash

    baremetal node service <node> --runbook CUSTOM_CONTAINER_CLEAN

Alternative Methods
===================

Operators may utilize container-based steps that are hardcoded via
configuration in-ramdisk.

Ironic-python-agent can be configured to expose arbitrary steps using
containers for use in workflows, including automated cleaning, via a
yaml configuration file.

For example:

.. code:: yaml

    steps:
      - name: manage_container_cleanup
        image: docker://172.24.4.1:5000/cleaning-image:latest
        interface: deploy
        reboot_requested: true
        pull_options:
          - --tls-verify=false
        run_options:
          - --rm
          - --network=host
          - --tls-verify=false
        abortable: true
        priority: 20
      - name: manage_container_cleanup2
        image: docker://172.24.4.1:5000/cleaning-image2:latest
        interface: deploy
        reboot_requested: true
        pull_options:
          - --tls-verify=false
        run_options:
          - --rm
          - --network=host
          - --tls-verify=false
        abortable: true
        priority: 10

By placing a file in your IPA ramdisk with these contents in
the path indicated by
:oslo.config:option:`agent_containers.container_steps_file`,
cleaning steps ``manage_container_cleanup`` and
``manage_container_cleanup2`` will be reported as available
cleaning steps at the indicated priority.

.. note::
   ``priority`` applies to **automated cleaning** only. The same steps are
   offered for deployment and servicing at priority ``0``, meaning they can
   be invoked explicitly from a runbook or deploy template but never run on
   their own. A non-zero priority would otherwise make a cleaning container
   run on every deployment, because a deploy step above priority zero runs
   automatically.

.. note::
   A step name must not match a step IPA already provides.
   ``erase_devices_metadata`` or ``write_image`` would shadow the real one;
   IPA reports a configuration error rather than running your container in
   its place.

This is useful for high-security environments which would prefer
the hassle of rebuilding a ramdisk to the risk of permitting
runtime decisions around what containers to clean with.

Security Considerations
=======================

Two kinds of container step, two levels of trust
------------------------------------------------

Container steps reach IPA by two different routes, and they are not trusted
equally:

**Steps baked into the ramdisk** via ``container_steps_file`` are authored by
the operator at image build time and cannot be changed at run time. They are
trusted and are not checked against ``allowed_containers``.

**Steps driven by step arguments**, such as from a runbook, deploy template,
manual cleaning or servicing, carry an image chosen by whoever made the API
call. These are untrusted and are checked against ``allowed_containers``
unless ``allow_arbitrary_containers`` is ``true``.

This matters because creating and using a runbook does not require full
administrative rights: ``baremetal:runbook:create`` is available to
``role:manager`` at project scope. Anyone who can run a runbook on a node can
therefore choose what executes as root on that node, bounded only by
``allowed_containers``.

General guidance
----------------

* **Prefer allowlisting** over ``allow_arbitrary_containers = true``.
  The allowlist (``allowed_containers``) restricts which images IPA will
  accept, reducing the risk of running untrusted code. The transport prefix
  is ignored when matching, so ``docker://example.com/tool:1`` and
  ``example.com/tool:1`` are the same entry.

* **Allowlist digests, not tags.** An entry naming a tag permits whatever
  that tag points at, so anyone able to push to the registry chooses what
  runs as root on your nodes. Only a pinned digest, such as
  ``example.com/tool@sha256:...``, actually constrains the content.

* **Options are part of the boundary.** When ``allow_arbitrary_containers``
  is ``false``, ``pull_options`` and ``run_options`` supplied as step
  arguments are ignored and the conductor's configured values are used.
  Flags alone are enough to defeat an image allowlist, since ``--privileged``,
  ``-v /:/host`` or ``--entrypoint`` turn any permitted image into arbitrary
  host access, so the caller who may not choose the image may not choose the
  flags either.

* **Step names must not collide** with existing hardware manager steps. A
  container step named after a real one, such as ``erase_devices_metadata``,
  would shadow it. IPA refuses such names, reporting a configuration error
  rather than silently substituting a container for the real step.

* **TLS verification** -- the default ``pull_options`` and ``run_options``
  include ``--tls-verify=false`` for development convenience. Remove it in
  production and make proper TLS certificates available in the ramdisk.
  Left in place it undoes the allowlist: anything able to answer for the
  registry can serve its own image under a permitted name.

* **Container privileges** -- by default, containers run with
  ``--network=host``, giving them full access to the node's network
  stack. Review ``run_options`` and consider adding ``--read-only`` or
  dropping capabilities where possible.

Troubleshooting
===============

Container pull failures
    Check that the container registry is accessible from the cleaning
    network. Verify the image URL in the runbook step. If using TLS,
    ensure certificates are configured correctly in the ramdisk or
    add ``--tls-verify=false`` to ``pull_options`` for testing.

Step not found: generic_container_step
    The IPA ramdisk was not built with the ``ironic-python-agent-podman``
    element. Rebuild the ramdisk with podman support as described in
    `Prerequisites`_.

Container image not permitted
    The container URL does not match any entry in ``allowed_containers``
    and ``allow_arbitrary_containers`` is ``false``. Either add the image
    to the allowlist or set ``allow_arbitrary_containers = true`` in
    ``[agent_containers]``. Note that steps baked into the ramdisk are not
    subject to the allowlist, so this only applies to images named in step
    arguments.

Container runtime is not available in this ramdisk
    ``[agent_containers]runner`` names a runtime the ramdisk does not
    contain. Either install it or change the option to match what was built
    into the image.

Container step collides with an existing hardware manager method
    A step in ``container_steps_file`` is named after a step IPA already
    provides and would shadow it. Rename the step in the YAML file.

Unknown flag, or the runtime rejects its arguments
    ``pull_options`` or ``run_options`` were written space separated. They
    are comma separated lists; see `Ironic Conductor Configuration`_.

Trait mismatch
    The node does not have a trait matching the runbook name. Add the
    trait with ``baremetal node add trait <node> <RUNBOOK_NAME>``.
