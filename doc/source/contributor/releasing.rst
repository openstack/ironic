=========================
Releasing Ironic Projects
=========================

Since the responsibility for releases will move between people, we document
that process here.

A full list of projects that ironic manages is available in the `governance
site`_.

.. _`governance site`: https://governance.openstack.org/reference/projects/ironic.html

Who is responsible for releases?
================================

The current PTL is ultimately responsible for making sure code gets released.
They may choose to delegate this responsibility to a liaison, which is
documented in the `cross-project liaison wiki`_.

Anyone may submit a release request per the process below, but the PTL or
liaison must +1 the request for it to be processed.

.. _`cross-project liaison wiki`: https://wiki.openstack.org/wiki/CrossProjectLiaisons#Release_management

Release process
===============

Releases are managed by the OpenStack release team. The release process is
documented in the `Project Team Guide`_.

.. _`Project Team Guide`: https://docs.openstack.org/project-team-guide/release-management.html#how-to-release

What do we have to release?
===========================

The ironic project has a number of deliverables under its governance.  The
ultimate source of truth for this is `projects.yaml
<https://opendev.org/openstack/governance/src/branch/master/reference/projects.yaml>`__
in the governance repository. These deliverables have varying release models,
and these are defined in the `deliverables YAML files
<https://opendev.org/openstack/releases/src/branch/master/deliverables>`__ in
the releases repository.

In general, ironic deliverables follow the `cycle-with-intermediary
<https://releases.openstack.org/reference/release_models.html#cycle-with-intermediary>`__
release model.

Non-client libraries
--------------------

The following deliverables are non-client libraries:

* ironic-lib
* metalsmith
* sushy

Client libraries
----------------

The following deliverables are client libraries:

* python-ironicclient
* python-ironic-inspector-client
* sushy-cli

Normal release
--------------

The following deliverables are Neutron plugins:

* networking-baremetal
* networking-generic-switch

The following deliverables are Horizon plugins:

* ironic-ui

The following deliverables are Tempest plugins:

* ironic-tempest-plugin

The following deliverables are services, or treated as such:

* bifrost
* ironic
* ironic-inspector
* ironic-prometheus-exporter
* ironic-python-agent

Independent
-----------

The following deliverables are released `independently
<https://releases.openstack.org/reference/release_models.html#independent>`__:

* ironic-python-agent-builder
* molteniron
* sushy-tools
* tenks
* virtualbmc

Not released
------------

The following deliverables do not need to be released:

* ironic-inspector-specs
* ironic-specs

Things to do before releasing
=============================

* Review the unreleased release notes, if the project uses them. Make sure
  they follow our :ref:`standards <faq_release_note>`, are coherent, and have
  proper grammar.
  Combine release notes if necessary (for example, a release note for a
  feature and another release note to add to that feature may be combined).

* For ironic releases only, not ironic-inspector releases: if any new API
  microversions have been added since the last release, update the REST API
  version history (``doc/source/contributor/webapi-version-history.rst``) to
  indicate that they were part of the new release.

* To support rolling upgrades, add this new release version (and release name
  if it is a named release) into ``ironic/common/release_mappings.py``:

  * in ``RELEASE_MAPPING`` make a copy of the ``master`` entry, and rename the
    first ``master`` entry to the new semver release version.

  * If this is a named release, add a ``RELEASE_MAPPING`` entry for the named
    release. Its value should be the same as that of the latest semver one
    (that you just added above).

    It is important to do this before a stable/<release> branch is made (or if
    `the grenade switch is made <http://lists.openstack.org/pipermail/openstack-dev/2017-February/111849.html>`_
    to use the latest release from stable as the 'old' release).
    Otherwise, once it is made, CI (the grenade job that tests new-release ->
    master) will fail.

* Check for any open patches that are close to be merged or release critical.

  This usually includes important bug fixes and/or features that we'd like to
  release, including the related documentation.

How to propose a release
========================

The steps that lead to a release proposal are mainly manual, while proposing
the release itself is almost a 100% automated process, accomplished by
following the next steps:

* Clone the `openstack/releases <https://opendev.org/openstack/releases>`_
  repository. This is where deliverables are tracked and all the automation
  resides.

  * Under the ``deliverables`` directory you can see yaml files for each
    deliverable (i.e. subproject) grouped by release cycles.

  * The ``_independent`` directory contains yaml files for deliverables that
    are not bound to (official) cycles (e.g. ironic-python-agent-builder).

* To check the changes we're about to release we can use the tox environment
  ``list-unreleased-changes``, with this syntax:

  .. code-block:: bash

    tox -e venv -- list-unreleased-changes <series> <deliverable>

  The ``series`` argument is a release series (i.e. master or train,
  not stable/ussuri or stable/train).

  For example, assuming we're in the main directory of the releases repository,
  to check the changes in the ussuri series for ironic-python-agent
  type:

  .. code-block:: bash

    tox -e venv -- list-unreleased-changes ussuri openstack/ironic-python-agent

* To update the deliverable file for the new release, we use a scripted process
  in the form of a tox environment called ``new-release``.

  To get familiar with it and see all the options, type:

  .. code-block:: bash

    tox -e venv -- new-release -h

  Now, based on the list of changes we found in the precedent step, and the
  release notes, we need to decide on whether the next version will be major,
  minor (feature) or patch (bugfix).

  Note that in this case ``series`` is a code name (train, ussuri), not a
  branch.

  The ``--stable-branch argument`` is used only for branching in the end of a
  cycle, independent projects are not branched this way though.

  To propose the release, use the script to update the deliverable file, then
  commit the change, and propose it for review.

  For example, to propose a minor release for ironic in the master branch use:

  .. code-block:: bash

    tox -e venv -- new-release -v master ironic feature

  Remember to use a meaningful topic, usually using the name of the
  deliverable, the new version and the branch, if applicable.

  A good commit message title should also include the same, for example
  "Release ironic 1.2.3 for ussuri"

* As an optional step, we can use ``tox -e list-changes`` to double-check the
  changes before submitting them for review.

  Also ``tox -e validate`` (it might take a while to run based on the number of
  changes) does some some sanity-checks, but since everything is scripted,
  there shouldn't be any issue.

  All the scripts are designed and maintained by the release team; in case of
  questions or doubts or if any errors should arise, you can reach to them in
  the IRC channel ``#openstack-release``; all release liaisons should be
  present there.

* After the change is up for review, the PTL or a release liaison will have to approve
  it before it can get approved by the release team. Then, it will be processed
  automatically by zuul.

Things to do after releasing
============================

When a release is done that results in a stable branch
------------------------------------------------------
When a release is done that results in a stable branch for the project,
several changes need to be made.

The release automation will push a number of changes that need to be approved.
This includes:

* In the new stable branch:

  * a change to point ``.gitreview`` at the branch
  * a change to update the upper constraints file used by ``tox``

* In the master branch:

  * updating the release notes RST to include the new branch.

    The generated RST does not include the version range in the title, so we
    typically submit a follow-up patch to do that. An example of this patch is
    `here <https://review.opendev.org/685070>`__.

  * update the `templates` in `.zuul.yaml` or `zuul.d/project.yaml`.

    The update is necessary to use the job for the next release
    `openstack-python3-<next_release>-jobs`. An example of this patch is
    `here <https://review.opendev.org/#/c/689705/>`__.

We need to submit patches for changes in the stable branch to:

* update the ironic devstack plugin to point at the branched tarball for IPA.
  An example of this patch is
  `here <https://review.opendev.org/685069/>`_.
* update links in the documentation (``ironic/doc/source/``) to point to the
  branched versions of any openstack projects' (that branch) documents.
  As of Pike release, the only outlier is
  `diskimage-builder <https://docs.openstack.org/diskimage-builder/latest/>`_.
* set appropriate defaults for ``TEMPEST_BAREMETAL_MIN_MICROVERSION`` and
  ``TEMPEST_BAREMETAL_MAX_MICROVERSION`` in ``devstack/lib/ironic`` to make sure
  that unsupported API tempest tests are skipped on stable branches. E.g.
  `patch 495319 <https://review.opendev.org/495319>`_.

We need to submit patches for changes on master to:

* create an empty commit with a ``Sem-Ver`` tag to bump the generated minor
  version. See `example
  <https://opendev.org/openstack/ironic/commit/4b28af4645c2f3b6d7864671e15904ed8f40414d>`_
  and `pbr documentation
  <https://docs.openstack.org/pbr/latest/user/features.html#version>`_ for details.

* to support rolling upgrades, since the release was a named release, we
  need to make these changes. Note that we need to wait until *after* the
  switch in grenade is made to test the latest release (N) with master
  (e.g. `for stable/queens <https://review.opendev.org/#/c/543615>`_).
  Doing these changes sooner -- after the ironic release and before the switch
  when grenade is testing the prior release (N-1) with master, will cause
  the tests to fail. (You may want to ask/remind infra/qa team, as to
  when they will do this switch.)

  * In ``ironic/common/release_mappings.py``, delete any entries from
    ``RELEASE_MAPPING`` associated with the oldest named release. Since we
    support upgrades between adjacent named releases, the master branch will
    only support upgrades from the most recent named release to master.

  * remove any DB migration scripts from ``ironic.cmd.dbsync.ONLINE_MIGRATIONS``
    and remove the corresponding code from ironic. (These migration scripts
    are used to migrate from an old release to this latest release; they
    shouldn't be needed after that.)

  * remove any model class names from ``ironic.cmd.dbsync.NEW_MODELS``.

As **ironic-tempest-plugin** is branchless, we need to submit a patch adding
stable jobs to its master branch. `Example for Queens
<https://review.opendev.org/#/c/543555/>`_.

For all releases
----------------

For all releases, whether or not it results in a stable branch:

* update the specs repo to mark any specs completed in the release as
  implemented.

* remove any -2s on patches that were blocked until after the release.
