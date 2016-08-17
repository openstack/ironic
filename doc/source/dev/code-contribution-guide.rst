.. _code-contribution-guide:

=======================
Code Contribution Guide
=======================

This document provides some necessary points for developers to consider when
writing and reviewing Ironic code. The checklist will help developers get
things right.

Getting Started
===============

If you're completely new to OpenStack and want to contribute to the ironic
project, please start by familiarizing yourself with the `Infra Team's Developer
Guide <http://docs.openstack.org/infra/manual/developers.html>`_. This will help
you get your accounts set up in Launchpad and Gerrit, familiarize you with the
workflow for the OpenStack continuous integration and testing systems, and help
you with your first commit.

LaunchPad Project
-----------------

Most of the tools used for OpenStack require a launchpad.net ID for
authentication.

.. seealso::

   * https://launchpad.net
   * https://launchpad.net/ironic

Related Projects
----------------

There are several projects that are tightly integrated with ironic and which are
developed by the same community.

.. seealso::

   * https://launchpad.net/bifrost
   * https://launchpad.net/ironic-inspector
   * https://launchpad.net/ironic-lib
   * https://launchpad.net/ironic-python-agent
   * https://launchpad.net/python-ironicclient
   * https://launchpad.net/python-ironic-inspector-client

Project Hosting Details
-----------------------

Bug tracker
    http://launchpad.net/ironic

Mailing list (prefix Subject line with ``[ironic]``)
    http://lists.openstack.org/cgi-bin/mailman/listinfo/openstack-dev

Wiki
    http://wiki.openstack.org/Ironic

Code Hosting
    https://git.openstack.org/cgit/openstack/ironic

Code Review
    https://review.openstack.org/#/q/status:open+project:openstack/ironic,n,z

Adding New Features
===================

Starting with the Mitaka development cycle, Ironic tracks new features using
RFEs (Requests for Feature Enhancements) instead of blueprints. These are bugs
with 'rfe' tag, and they should be submitted before a spec or code is proposed.
When a member of `ironic-drivers launchpad team
<https://launchpad.net/~ironic-drivers/+members>`_ decides that the proposal
is worth implementing, a spec (if needed) and code should be submitted,
referencing the RFE bug. Contributors are welcome to submit a spec and/or code
before the RFE is approved, however those patches will not land until the RFE
is approved.

Here is a list of steps to do during the new process of adding a new feature to
Ironic:

#. Submit a bug report at https://bugs.launchpad.net/ironic/+filebug.
   There are two fields that must be filled: 'summary' and
   'further information'. The 'summary' must be brief enough to fit in one
   line: if you can’t describe it in a few words it may mean that you are
   either trying to capture more than one RFE at once, or that you are having
   a hard time defining what you are trying to solve at all.

#. Describe the proposed change in the 'further information' field. The
   description should provide enough details for a knowledgeable developer to
   understand what is the existing problem in the current platform that needs
   to be addressed, or what is the enhancement that would make the platform
   more capable, both from a functional and a non-functional standpoint.

#. Submit the bug, add an 'rfe' tag to it and assign yourself or whoever is
   going to work on this feature.

#. As soon as a member of the ironic-drivers team acknowledges the bug, it
   will be moved into the 'Triaged' state. The importance will be set to
   'Wishlist' to signal the fact that the report is indeed a feature and there
   is no severity associated to it. Discussion about the RFE, and whether to
   approve it, happens in bug comments while in the 'Triaged' state.

#. The ironic-drivers team will evaluate the RFE and may advise the submitter
   to file a spec in ironic-specs to elaborate on the feature request, in case
   the RFE requires extra scrutiny, more design discussion, etc. For the spec
   submission process, please see the `Ironic Specs Process`_.

#. If a spec is not required, once the discussion has happened and there is
   positive consensus among the ironic-drivers team on the RFE, the RFE is
   'approved', and its tag will move from 'rfe' to 'rfe-approved'. This means
   that the feature is approved and the related code may be merged.

#. If a spec is required, the spec must be submitted (with the bug properly
   referenced as 'Partial-Bug' in the commit message), reviewed, and merged
   before the RFE will be 'approved' (and the tag changed to 'rfe-approved').

#. The bug then goes through the usual process -- first to 'In progress' when
   the spec/code is being worked on, then 'Fix Released' when it is
   implemented.

#. If the RFE is rejected, the ironic-drivers team will move the bug to
   "Won't Fix" status.

When working on an RFE, please be sure to tag your commits properly:
"Partial-Bug: #xxxx" or "Related-Bug: #xxxx" for intermediate commits for the
feature, and "Closes-Bug: #xxxx" for the final commit. It is also helpful to
set a consistent review topic, such as "bug/xxxx" for all patches related to
the RFE.

If the RFE spans across several projects (e.g. ironic and python-ironicclient),
but the main work is going to happen within ironic, please use the same bug for
all the code you're submitting, there is no need to create a separate RFE in
every project.

Note that currently the Ironic bug tracker is managed by the open 'ironic-bugs'
team, not the ironic-drivers team. This means that anyone may edit bug details,
and there is room to game the system here. **RFEs may only be approved by
members of the ironic-drivers team**. Attempts to sneak around this rule will
not be tolerated, and will be called out in public on the mailing list.


Live Upgrade Related Concerns
=============================
Ironic implements upgrade with the same methodology of Nova:
    http://docs.openstack.org/developer/nova/upgrade.html

Ironic API RPC Versions
-----------------------

*  When the signature(arguments) of an RPC method is changed, the following things
   need to be considered:

 - The RPC version must be incremented and be the same value for both the client
   (conductor/rpcapi.py, used by ironic-api) and the server (conductor/manager.py,
   used by ironic-conductor).
 - New arguments of the method can only be added as optional. Existing arguments cannot be
   removed or changed in incompatible ways (with the method in older RPC versions).
 - Client-side can pin a version cap by passing ``version_cap`` to the constructor
   of oslo_messaging.RPCClient. Methods which change arguments should run
   client.can_send_version() to see if the version of the request is compatible with the
   version cap of RPC Client, otherwise the request needs to be created to work with a
   previous version that is supported.
 - Server-side should tolerate the older version of requests in order to keep
   working during the progress of live upgrade. The behavior of server-side should
   depend on the input parameters passed from the client-side.

Object Versions
---------------
* When Object classes (subclasses of ironic.objects.base.IronicObject) are modified, the
  following things need to be considered:

 - The change of fields and the signature of remotable method needs a bump of object
   version.
 - The arguments of methods can only be added as optional, they cannot be
   removed or changed in an incompatible way.
 - Fields types cannot be changed. If it is a must, create a new field and
   deprecate the old one.
 - When new version objects communicate with old version objects,
   obj_make_compatible() will be called to convert objects to the target version during
   serialization. So objects should implement their own obj_make_compatible() to
   remove/alter attributes which was added/changed after the target version.
 - There is a test (object/test_objects.py) to generate the hash of object fields and the
   signatures of remotable methods, which helps developers to check if the change of
   objects need a version bump. The object fingerprint should only be updated with a
   version bump.

Driver Internal Info
====================
The ``driver_internal_info`` node field was introduced in the Kilo release. It allows
driver developers to store internal information that can not be modified by end users.
Here is the list of existing common and agent driver attributes:

Common attributes:
  * ``is_whole_disk_image``: A Boolean value to indicate whether the user image contains ramdisk/kernel.
  * ``clean_steps``: An ordered list of clean steps that will be performed on the node.
  * ``instance``: A list of dictionaries containing the disk layout values.
  * ``root_uuid_or_disk_id``: A String value of the bare metal node's root partition uuid or disk id.
  * ``persistent_boot_device``: A String value of device from ``ironic.common.boot_devices``.
  * ``is_next_boot_persistent``: A Boolean value to indicate whether the next boot device is
    ``persistent_boot_device``.

Agent driver attributes:
  * ``agent_url``: A String value of IPA API URL so that Ironic can talk to IPA ramdisk.
  * ``agent_last_heartbeat``: An Integer value of the last agent heartbeat time.
  * ``hardware_manager_version``: A String value of the version of the hardware manager in IPA ramdisk.
  * ``target_raid_config``: A Dictionary containing the target RAID configuration. This is a copy of
    the same name attribute in Node object. But this one is never actually saved into DB and is only
    read by IPA ramdisk.

.. note::

    These are only some fields in use. Other vendor drivers might expose more ``driver_internal_info``
    properties, please check their development documentation and/or module docstring for details.
    It is important for developers to make sure these properties follow the precedent of prefixing their
    variable names with a specific interface name (e.g., iboot_bar, amt_xyz), so as to minimize or avoid
    any conflicts between interfaces.


Ironic Specs Process
====================

Specifications must follow the template which can be found at
`specs/template.rst <http://git.openstack.org/cgit/openstack/ironic-specs/tree/
specs/template.rst>`_, which is quite self-documenting. Specifications are
proposed by adding them to the `specs/approved` directory, adding a soft link
to it from the `specs/not-implemented` directory, and posting it for
review to Gerrit. For more information, please see the `README <http://git.
openstack.org/cgit/openstack/ironic-specs/tree/README.rst>`_.

The same `Gerrit process
<http://docs.openstack.org/infra/manual/developers.html>`_ as with source code,
using the repository `ironic-specs <http://git.openstack.org/cgit/openstack/
ironic-specs/>`_, is used to add new specifications.

All approved specifications are available at:
http://specs.openstack.org/openstack/ironic-specs. If a specification has
been approved but not completed within one or more releases since the
approval, it may be re-reviewed to make sure it still makes sense as written.

Ironic specifications are part of the `RFE (Requests for Feature Enhancements)
process <#adding-new-features>`_.
You are welcome to submit patches associated with an RFE, but they will have
a -2 ("do not merge") until the specification has been approved. This is to
ensure that the patches don't get accidentally merged beforehand. You will
still be able to get reviewer feedback and push new patch sets, even with a -2.
The `list of core reviewers <https://review.openstack.org/#/admin/groups/352,
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
