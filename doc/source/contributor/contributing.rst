.. _code-contribution-guide:

============================
So You Want to Contribute...
============================

This document provides some necessary points for developers to consider when
writing and reviewing Ironic code. The checklist will help developers get
things right. Please make sure to check the :doc:`community page <community>`
first.

Contributing Code
=================

If you're completely new to OpenStack and want to contribute to the ironic
project, please start by familiarizing yourself with the `Infra Team's Developer
Guide <https://docs.openstack.org/infra/manual/developers.html>`_. This will
help you get your accounts set up in Launchpad and Gerrit, familiarize you with
the workflow for the OpenStack continuous integration and testing systems, and
help you with your first commit.

Everything Ironic
-----------------

Ironic is a community of projects centered around the primary project
repository 'ironic', which help facilitate the deployment and management
of bare metal resources.

This means there are a number of different repositories that fall into
the responsibility of the project team and the community. Some of the
repositories may not seem strictly hardware related, but they may be tools
or things to just make an aspect easier.

Related Projects
----------------

There are several projects that are tightly integrated with ironic and
which are developed by the same community.

.. seealso::

   * :bifrost-doc:`Bifrost Documentation <>`
   * :ironic-inspector-doc:`Ironic Inspector Documentation <>`
   * :ironic-lib-doc:`Ironic Lib Documentation <>`
   * :ironic-python-agent-doc:`Ironic Python Agent (IPA) Documentation <>`
   * :python-ironicclient-doc:`Ironic Client Documentation <>`
   * :python-ironic-inspector-client-doc:`Ironic Inspector Client Documentation <>`

Adding New Features
===================

Ironic tracks new features using RFEs (Requests for Feature Enhancements)
instead of blueprints. These are stories with 'rfe' tag, and they should
be submitted before a spec or code is proposed.

When a member of the `ironic-core team <https://review.opendev.org/#/admin/groups/165,members>`_
decides that the proposal is worth implementing, a spec (if needed) and code
should be submitted, referencing the RFE task or bug number. Contributors
are welcome to submit a spec and/or code before the RFE is approved, however
those patches will not land until the RFE is approved.

Feature Submission Process
--------------------------

#. Submit a bug report on `Launchpad
   <https://bugs.launchpad.net/ironic/+bugs>`_.
   If you can't describe your feature in a sentence or two, it may mean that
   you are either trying to capture more than one RFE at once, or that you are
   having a hard time defining what you are trying to solve at all. This may
   also be a sign that your feature may require a specification document.

#. Describe the proposed change in the 'Description' field. The
   description should provide enough details for a knowledgeable developer to
   understand what is the existing problem in the current platform that needs
   to be addressed, or what is the enhancement that would make the platform
   more capable, both from a functional and a non-functional standpoint.

#. Submit the bug, add an 'rfe' tag to it and assign yourself or whoever is
   going to work on this feature.

#. As soon as a member of the team acknowledges the bug,
   we will move it to the 'Review' state. As time goes on, Discussion
   about the RFE, and whether to approve it will occur. If the RFE has not
   been triaged and you'd like it to recieve immediate attention, add it to
   the Open Discussion section of our
   `weekly meeting agenda <https://wiki.openstack.org/wiki/Meetings/Ironic>`,
   and, timezone permitting, attend the meeting to advocate for your RFE.

#. Contributors will evaluate the RFE and may advise the submitter to file a
   spec in the ironic-specs repository to elaborate on the feature request.
   Typically this is when an RFE requires extra scrutiny, more design
   discussion, etc. For the spec submission process, please see the
   `Ironic Specs Process`_. A specific task should be created to track the
   creation of a specification.

#. If a spec is not required, once the discussion has happened and there is
   positive consensus among the ironic-core team on the RFE, the RFE is
   'approved', and its tag will move from 'rfe' to 'rfe-approved'. This means
   that the feature is approved and the related code may be merged.

#. If a spec is required, the spec must be submitted (with a new task as part
   of the story referenced as 'Task' in the commit message), reviewed, and merged
   before the RFE will be 'approved' (and the tag changed to 'rfe-approved').

#. If the RFE is rejected, the ironic-core team will move the story to
   "Invalid" status.

Change Tracking
---------------

Please ensure work related to a bug or RFE is tagged with the bug. This
generally is a "Closes-bug", "Partial-bug" or "Related-bug" tag as described
in the
`Git Commit messages guide <https://wiki.openstack.org/wiki/GitCommitMessages#Including_external_references>``.

.. note:: **RFEs may only be approved by members of the ironic-core team**.

.. note:: While not strictly required for minor changes and fixes,
          it is highly preferred by the Ironic community that any change
          which needs to be backported, have a recorded bug.

Managing Change Sets
--------------------

If you would like some help, or if you (or some members of your team)
are unable to continue working on the feature, updating and
maintaining the changes, please let the rest of the ironic community
know. You could leave a comment in one or more of the
changes/patches, bring it up in IRC, the weekly meeting,
or on the OpenStack development email list.
Communicating this will make other contributors aware of the
situation and allow for others to step forward and volunteer to
continue with the work.

In the event that a contributor leaves the community, do not expect
the contributor's changes to be continued unless someone volunteers
to do so.

Getting Your Patch Merged
-------------------------

Within the Ironic project, we generally require two core reviewers to
sign-off (+2) change sets. We also will generally recognize non-core (+1)
reviewers, and sometimes even reverse our decision to merge code based upon their reviews.

We recognize that some repositories have less visibility, as such it is okay
to ask for a review in our IRC channel. Please be prepared to stay in IRC
for a little while in case we have questions.

Sometimes we may also approve patches with a single core reviewer.
This is generally discouraged, but sometimes necessary. When we do so,
we try to explain why we do so. As a patch submitter, it equally helps us
to understand why the change is important. Generally, more detail and context
helps us understand the change faster.

Timeline Expectations
---------------------

As with any large project, it does take time for features and changes to be
merged in any of the project repositories. This is largely due to limited
review bandwidth coupled with varying reviewer priorities and focuses.

When establishing an understanding of complexity, the following things should
be kept in mind.

* Generally, small and minor changes can gain consensus and merge fairly
  quickly. These sorts of changes would be: bug fixes, minor documentation
  updates, follow-up changes.

* Medium changes generally consist of driver feature parity changes,
  where one driver is working to match functionality of another driver.

  * These changes generally only require an RFE for the purposes of
    tracking and correlating the change.
  * Documentation updates are expected to be submitted with or immediately
    following the initial change set.

* Larger or controversial changes generally take much longer to merge.
  This is often due to the necessity of reviewers to gain additional
  context and for change sets to be iterated upon to reach a state
  where there is consensus. These sorts of changes include: database,
  object, internal interface additions, RPC, rest API changes.

  * These changes will very often require specifications to reach
    consensus, unless there are pre-existing patterns or code already
    present.
  * These changes may require many reviews and iterations, and can
    also expect to be impacted by merge conflicts as other code or
    features are merged.
  * These changes must typically be split into a series of changes.
    Reviewers typically shy away from larger single change sets due
    to increased difficulty in reviewing.
  * Do not expect any API or user-visible data model changes to merge
    after the API client freeze. Some substrate changes may merge if
    not user visible.

* You should expect complex features, such as cross-project features
  or integration, to take longer than a single development cycle to land.

  * Building consensus is vital.
  * Often these changes are controversial or have multiple
    considerations that need to be worked through in the specification
    process, which may cause the design to change. As such, it may
    take months to reach consensus over design.
  * These features are best broken into larger chunks and tackled
    in an incremental fashion.

Live Upgrade Related Concerns
-----------------------------

See :doc:`/contributor/rolling-upgrades`.

Driver Internal Info
~~~~~~~~~~~~~~~~~~~~
The ``driver_internal_info`` node field was introduced in the Kilo release. It allows
driver developers to store internal information that can not be modified by end users.
Here is the list of existing common and agent driver attributes:

* Common attributes:

  * ``is_whole_disk_image``: A Boolean value to indicate whether the user image contains ramdisk/kernel.
  * ``clean_steps``: An ordered list of clean steps that will be performed on the node.
  * ``deploy_steps``: An ordered list of deploy steps that will be performed on the node. Support for
    deploy steps was added in the ``11.1.0`` release.
  * ``instance``: A list of dictionaries containing the disk layout values.
  * ``root_uuid_or_disk_id``: A String value of the bare metal node's root partition uuid or disk id.
  * ``persistent_boot_device``: A String value of device from ``ironic.common.boot_devices``.
  * ``is_next_boot_persistent``: A Boolean value to indicate whether the next boot device is
    ``persistent_boot_device``.

* Agent driver attributes:

  * ``agent_url``: A String value of IPA API URL so that Ironic can talk to IPA
    ramdisk.
  * ``hardware_manager_version``: A String value of the version of the hardware
    manager in IPA ramdisk.
  * ``target_raid_config``: A Dictionary containing the target RAID
    configuration. This is a copy of the same name attribute in Node object.
    But this one is never actually saved into DB and is only read by IPA ramdisk.

.. note::

    These are only some fields in use. Other vendor drivers might expose more ``driver_internal_info``
    properties, please check their development documentation and/or module docstring for details.
    It is important for developers to make sure these properties follow the precedent of prefixing their
    variable names with a specific interface name (e.g., ilo_bar, drac_xyz), so as to minimize or avoid
    any conflicts between interfaces.


Ironic Specs Process
--------------------

Specifications must follow the template which can be found at
`specs/template.rst <https://opendev.org/openstack/ironic-specs/src/branch/
master/specs/template.rst>`_, which is quite self-documenting. Specifications are
proposed by adding them to the `specs/approved` directory, adding a soft link
to it from the `specs/not-implemented` directory, and posting it for
review to Gerrit. For more information, please see the `README <https://git.
openstack.org/cgit/openstack/ironic-specs/tree/README.rst>`_.

The same `Gerrit process
<https://docs.openstack.org/infra/manual/developers.html>`_ as with source code,
using the repository `ironic-specs <https://opendev.org/openstack/
ironic-specs/>`_, is used to add new specifications.

All approved specifications are available at:
https://specs.openstack.org/openstack/ironic-specs. If a specification has
been approved but not completed within one or more releases since the
approval, it may be re-reviewed to make sure it still makes sense as written.

Ironic specifications are part of the `RFE (Requests for Feature Enhancements)
process <#adding-new-features>`_.
You are welcome to submit patches associated with an RFE, but they will have
a -2 ("do not merge") until the specification has been approved. This is to
ensure that the patches don't get accidentally merged beforehand. You will
still be able to get reviewer feedback and push new patch sets, even with a -2.
The `list of core reviewers <https://review.opendev.org/#/admin/groups/352,
members>`_ for the specifications is small but mighty. (This is not
necessarily the same list of core reviewers for code patches.)

Changes to existing specs
-------------------------

For approved but not-completed specs:

- cosmetic cleanup, fixing errors, and changing the definition of a feature
  can be done to the spec.

For approved and completed specs:

- changing a previously approved and completed spec should only be done
  for cosmetic cleanup or fixing errors.
- changing the definition of the feature should be done in a new spec.


Please see the `Ironic specs process wiki page <https://wiki.openstack.org/
wiki/Ironic/Specs_Process>`_ for further reference.

Project Team Leader Duties
==========================

The ``Project Team Leader`` or ``PTL`` is elected each development
cycle by the contributors to the ironic community.

Think of this person as your primary contact if you need to try and
rally the project, or have a major issue that requires attention.

They serve a role that is mainly oriented towards trying to drive the
technical discussion forward and managing the idiosyncrasies of the project.
With this responsibility, they are considered a "public face" of the project
and are generally obliged to try and provide "project updates" and outreach
communication.

All common PTL duties are enumerated here in the `PTL guide <https://docs.openstack.org/project-team-guide/ptl.html>`_.

Tasks like release management or preparation for a release are generally
delegated with-in the team. Even outreach can be delegated, and specifically
there is no rule stating that any member of the community can't propose a
release, clean-up release notes or documentation, or even get on the occasional
stage.
