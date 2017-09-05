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

Things to do before releasing
=============================

* Review the unreleased release notes, if the project uses them. Make sure
  they follow our :ref:`standards <faq_release_note>`, are coherent, and have
  proper grammar.
  Combine release notes if necessary (for example, a release note for a
  feature and another release note to add to that feature may be combined).

* For ironic releases only, not ironic-inspector releases: if any new API
  microversions have been added since the last release, update the REST API
  version history (doc/source/contributor/webapi-version-history.rst) to
  indicate that they were part of the new release.

* To support rolling upgrades, add this new release version (and release name
  if it is a named release) into ironic/common/release_mappings.py:

  * in RELEASE_MAPPING, make a copy of the 'master' entry, and rename the first
    'master' entry to the new semver release version.
  * If this is a named release, add a RELEASE_MAPPING entry for the named
    release. Its value should be the same as that of the latest semver one
    (that you just added above).
  * Regenerate the sample config file, so that the choices for the
    ``[DEFAULT]/pin_release_version`` configuration are accurate.

Things to do after releasing
============================

When a release is done that results in a stable branch
------------------------------------------------------

When a release is done that results in a stable branch for the project, the
release automation will push a number of changes that need to be approved.

In the new stable branch, this will include:

* a change to point .gitreview at the branch
* a change to update the upper constraints file used by tox

In the master branch, this will include:

* updating the release notes RST to include the new branch

Additionally, changes need to be made to the stable branch to:

* update the ironic devstack plugin to point at the branched tarball for IPA.
  An example of this patch is
  `here <https://review.openstack.org/#/c/374863/>`_.
* update links in developer documentation to point to the branched version
  of the install guide.
* update links in the install guide to point to the branched version of
  the developer documentation.
* set appropriate defaults for TEMPEST_BAREMETAL_MIN_MICROVERSION and
  TEMPEST_BAREMETAL_MAX_MICROVERSION in devstack/lib/ironic to make sure that
  unsupported API tempest tests are skipped on stable branches.

Additionally, changes need to be made on master to:

* create an empty commit with a ``Sem-Ver`` tag to bump the generated minor
  version. See `example
  <https://git.openstack.org/cgit/openstack/ironic/commit/?id=4b28af4645c2f3b6d7864671e15904ed8f40414d>`_
  and `pbr documentation
  <https://docs.openstack.org/pbr/latest/user/features.html#version>`_ for details.

* to support rolling upgrades, since the release was a named release:

  * In ironic/common/release_mappings.py, delete any entries from RELEASE_MAPPING
    associated with the oldest named release. Since we support upgrades between
    adjacent named releases, the master branch will only support upgrades from
    the most recent named release to master.

  * regenerate the sample config file, so that the choices for the
    ``[DEFAULT]/pin_release_version`` configuration are accurate.

  * remove any DB migration scripts from ironic.cmd.dbsync.ONLINE_MIGRATIONS
    and remove the corresponding code from ironic. (These migration scripts
    are used to migrate from an old release to this latest release; they
    shouldn't be needed after that.)

For all releases
----------------

For all releases, whether or not it results in a stable branch:

* update the specs repo to mark any specs completed in the release as
  implemented.

* remove any -2s on patches that were blocked until after the release.
