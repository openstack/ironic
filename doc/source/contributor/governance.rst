===========================
Ironic Governance Structure
===========================

The ironic project manages a number of repositories that contribute to
our mission. The full list of repositories that ironic manages is available
in the `governance site`_.

.. _`governance site`: https://governance.openstack.org/reference/projects/ironic.html

What belongs in ironic governance?
==================================

For a repository to be part of the Ironic project:

* It must comply with the TC's `rules for a new project
  <https://governance.openstack.org/reference/new-projects-requirements.html>`_.
* It must not be intended for use with only a single vendor's hardware.
  A library that implements a standard to manage hardware from multiple
  vendors (such as IPMI or redfish) is okay.
* It must align with Ironic's `mission statement
  <https://governance.openstack.org/reference/projects/ironic.html#mission>`_.

Lack of contributor diversity is a chicken-egg problem, and as such a
repository where only a single company is contributing is okay, with the hope
that other companies will contribute after joining the ironic project.

Repositories that are no longer maintained should be pruned from governance
regularly.

Proposing a new project to ironic governance
============================================

Bring the proposal to the ironic `weekly meeting
<https://wiki.openstack.org/wiki/Meetings/Ironic>`_ to discuss with the team.
