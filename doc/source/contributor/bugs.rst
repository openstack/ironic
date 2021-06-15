Bug Reporting and Triaging Guide
================================

StoryBoard
----------

All ironic projects use StoryBoard_ for tracking both bugs and enhancement
requests (RFE). The `ironic project group`_ lists all our projects.

.. note::
   Ironic is developed as part of OpenStack and therefore uses
   the ``openstack/`` namespace.

StoryBoard is somewhat different from traditional bug tracking
systems because every *story* is not linked to a project itself, but rather
through its *tasks*. A story represents an issue you are facing or an
enhancement you want to see, while tasks represent individual action items
which can span several projects. When creating a story, you'll also need to
create the first task. If unsure, create a task against ``openstack/ironic``.

Reporting Guide
---------------

We are constantly receiving a lot of requests, so it's important to file a
meaningful story for it to be acted upon. A good story:

* specifies **why** a change is needed. In case of a bug - what you expected
  to happen.

* explains how to reproduce the described condition.

  .. note::
     Please try to provide a reproducer based on unit tests, :ref:`devstack
     <deploy_devstack>` or bifrost_. While we try our best to support users
     using other installers and distributions, it may be non-trivial without
     deep knowledge of them. If you're using a commercial distribution or
     a product, please try contacting support first.

* should be understandable without additional context. For example, if you see
  an exception, we will need the full traceback. Other commonly required
  things are:

  * the contents of the node in question (use ``baremetal node show <uuid>``)
  * debug logging related to the event, ideally with logs from the ramdisk
  * versions of ironic, ironic-python-agent, and any other coupled components.

* should not be too verbose either. Unfortunately, we cannot process a few days
  worth of system logs to find the problems, we expect your collaboration.

* is not a question or a support request. Please see :doc:`contributing` for
  the ways to contact us.

* provides a way to contact the reporter. Please follow the comments and
  expect follow-up emails, but ideally also be on IRC for questions.

An enhancement request additionally:

* benefits the overall project, not just one consumer. If you have a case that
  is specific to your requirements, think about ways to make ironic extensible
  to be able to cover it.

* does not unnecessary increase the project scope. Consider if your idea can be
  implemented without changing ironic or its projects, maybe it actually
  should?

Triaging Guide
--------------

The bug triaging process involves checking new stories to make sure they are
actionable by the team. This guide is mostly targeting the project team, but we
would appreciate if reporters could partly self-triage their own requests.

* Determine if the request is valid and complete. Use the checklist in the
  `Reporting Guide`_ for that.

* Is the request a bug report or an enhancement request (an RFE)? The
  difference is often subtle, the key question to answer is if the described
  behavior is expected.

  Add an ``rfe`` tag to all enhancement requests and propose it for the "RFE
  Review" section of the `weekly meeting`_.

* Does the RFE obviously require a spec_? Usually this is decided when an RFE
  is reviewed during the meeting, but some requests are undoubtedly complex,
  involve changing a lot of critical parts and thus demand a spec.

  Add a ``needs-spec`` tag to enhancement requests that obviously need a
  spec. Otherwise leave it until the meeting.

* Apply additional tags:

  * All hardware type specific stories should receive a corresponding tag (e.g.
    ``ipmi``, ``idrac``, etc).

  * API-related stories should have an ``api`` tag.

  * CI issues should have a ``gate`` tag.

The next actions **must only** be done by a core team member (or an experienced
full-time contributor appoined by the PTL):

* Can the RFE be automatically approved? It happens if the RFE requests an
  implementation of a driver feature that is already implemented for other
  drivers and does not pose additional complexity.

  If the RFE can be automatically approved, apply the ``rfe-approved`` tag.
  If unsure, never apply the tag! Talk to the PTL instead.

* Does the RFE have a corresponding spec approved? If yes, apply the
  ``rfe-approved`` tag.

* In the end, apply the ``ironic-triaged`` tag to make the story as triaged.

Expiring Bugs
-------------

While we hope to fix all issues that our consumers hit, it is unfortunately not
realistic. Stories **may** be closed by marking all their tasks ``INVALID`` in
the following cases:

* No solution has been proposed in 1 calendar year.

* Additional information has been requested from the reporter, and no update
  has been provided in 1 calendar month.

* The request no longer aligns with the direction of the project.

.. note::
   As usual, common sense should be applied when closing stories.

.. _StoryBoard: https://storyboard.openstack.org
.. _ironic project group: https://storyboard.openstack.org/#!/project_group/ironic
.. _bifrost: https://docs.openstack.org/bifrost
.. _spec: https://specs.openstack.org/openstack/ironic-specs/
.. _weekly meeting: https://wiki.openstack.org/wiki/Meetings/Ironic
