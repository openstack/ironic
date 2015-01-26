What is this file?
==================

This file is a loosely-organized list of some of the high-level and long-term
goals of the project's core development team.

It is *not* a list of specific tasks or ongoing work - for that, please see the
list of blueprints targeted to the current release cycle, here:
  https://launchpad.net/ironic/


Some of the Big Things we're working on
=======================================

* Implementing a formal model for Node states.

* Node introspection (discover properties of a known Node)
  See https://github.com/stackforge/ironic-discoverd

* Support RAID and firmware management

* Improving the Agent deploy driver so that we can deprecate
  the current "pxe" driver (which is really pxe-boot + iscsi-deploy).
