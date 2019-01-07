.. _vision_reflection:

=================================================
Comparison to the 2018 OpenStack Technical Vision
=================================================

In late-2018, the OpenStack Technical composed a
`technical vision <https://governance.openstack.org/tc/reference/technical-vision.html>`_
of what OpenStack clouds should look like. While every component differs, and
"cloudy" interactions change dramatically the closer to physical hardware one
gets, there are a few areas where Ironic could use some improvement.

This list is largely for the purposes of help wanted. It is also
important to note that Ironic as a project has a
`vision document <vision.html>`_ for itself.

The Pillars of Cloud - Self Service
===================================

* Ironic's mechanisms and tooling are low level infrastructure mechanisms
  and as such there has never been a huge emphasis or need on making
  Ironic be capable of offering direct multi-tenant interaction. Most users
  interact with the bare metal managed by Ironic via Nova, which abstracts
  away many of these issues. Eventually, we should offer direct multi-tenancy
  which is not oriented towards admin-only.

Design Goals - Built-in Reliability and Durability
==================================================

* Ironic presently considers in-flight operations as failed upon the restart
  of a controller that was previously performing a task, because we do not
  know the current status of the task upon re-start. In some cases, this makes
  sense, but potentially requires administrative intervention in the worst of
  cases. In a perfect universe, Ironic "conductors" would validate their
  perception, in case tasks actually finished.

Design Goals - Graphical User Interface
=======================================

* While a graphical interface was developed for Horizon in the form of
  `ironic-ui <https://git.openstack.org/cgit/openstack/ironic-ui>`_,
  currently ironic-ui receives only minimal housekeeping.
  As Ironic has evolved, ironic-ui is stuck on version `1.34` and knows
  nothing of our evolution since. Ironic ultimately needs a contributor
  with sufficient time to pick up ``ironic-ui`` or to completely
  replace it as a functional and customizable user interface.
