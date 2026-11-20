===============
Bugfix Branches
===============

This page describes the bugfix branches used by Ironic projects in addition to
the regular OpenStack ``stable/NAME`` branches.

Projects with bugfix branches
=============================

The following projects use ``bugfix/X.Y`` branches:

* ``ironic``
* ``ironic-python-agent``
* ``networking-generic-switch``

Cadence and eligibility
=======================

Projects receive their regular releases every six months as part of the
coordinated OpenStack release. These releases are made from a ``stable/NAME``
branch.

There is one evaluation for an additional bugfix release between scheduled
stable releases, 10–12 weeks after a stable release. This is an evaluation
point, not a commitment to create a branch or release. A bugfix release is
created only when there are significant beneficial changes and a known
downstream operator or distributor that will consume it.

Branching and versioning
========================

Bugfix branches are named ``bugfix/X.Y`` and are created from an intermediate
release that does not result in a regular ``stable/NAME`` branch. Releases from
``master`` must increase the major or minor version to leave version space for
patch releases from bugfix branches.

To propose a release that creates a bugfix branch, use the OpenStack release
tool's ``--intermediate-branch`` option. The release type should reflect the
changes in the release; releases from ``master`` should use a feature or major
version increment, while subsequent bugfix releases use patch versions. For
example:

.. code-block:: console

   tox -e venv -- new-release <series> <deliverable> feature --intermediate-branch

The ``series`` is the OpenStack release series name, not a branch name. The
release proposal is submitted to the ``openstack/releases`` repository and is
processed by the OpenStack release team after project approval.

The NGS deliverable must use ``stable-branch-type: std-with-versions`` in its
release metadata to support version-based ``bugfix/X.Y`` branches.

After a branch is created
=========================

The release tooling updates ``.gitreview`` to point to the new branch, but does
not update ``tox.ini`` for a bugfix branch. Update the upper-constraints link
used by tests and configure the requirements project to use the appropriate
constraints for the branch creation time. See `this example change
<https://review.opendev.org/c/openstack/ironic/+/938660>`__.

Zuul also needs configuration to select the appropriate job definitions for
the new branch. For examples, see the changes for `Ironic 18.1
<https://review.opendev.org/c/openstack/ironic/+/801876>`__ and
`ironic-python-agent 8.1
<https://review.opendev.org/c/openstack/ironic-python-agent/+/801898>`__.

For Ironic, set the ``TEMPEST_BAREMETAL_MIN_MICROVERSION`` and
``TEMPEST_BAREMETAL_MAX_MICROVERSION`` defaults in ``devstack/lib/ironic`` so
unsupported API tests are skipped on the branch. Remove or disable the metal3
integration and codespell jobs on Ironic stable and bugfix branches. The
remaining metal3 jobs may need updates as the Metal3 community releases;
instructions are in the job definitions.

Releasing from a bugfix branch
==============================

Bugfix releases are proposed through the ``openstack/releases`` repository,
like other OpenStack releases, selecting a patch (bugfix) release from the
branch. The ``--intermediate-branch`` option is only needed when creating the
branch, not for its later patch releases.

For general release preparation and proposal instructions, see
:doc:`releasing`.

Support and retirement
======================

A bugfix branch is supported for six months after its creation. Branches that
have reached end-of-life (EOL) should be tagged and deleted. When creating a
new bugfix branch, retire the oldest branch as needed.

Retirement is currently a manual process. Only members of the
``ironic-core`` or ``ironic-release`` groups can delete branches. To retire a
branch:

#. Check out the bugfix branch locally, tracking the remote branch if needed:

   .. code-block:: console

      git checkout -t origin/bugfix/X.Y

#. Fast-forward to the latest change:

   .. code-block:: console

      git pull --ff-only

#. Add a signed EOL tag to the latest commit:

   .. code-block:: console

      git tag -s bugfix-X.Y-eol -m "EOL bugfix/X.Y"

#. Push the tag and delete the branch on Gerrit:

   .. code-block:: console

      git push gerrit bugfix-X.Y-eol
      git push gerrit --delete bugfix/X.Y
