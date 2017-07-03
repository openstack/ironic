.. _third-party-ci:

==================================
Third Party Continuous Integration
==================================

.. NOTE:: This document is a work-in-progress. Unfilled sections will be
   worked in follow-up patchsets. This version is to get a basic outline and
   index done so that we can then build on it. (krtaylor)

This document provides tips and guidelines for third-party driver developers
setting up their continuous integration test systems.

CI Architecture Overview
========================

Requirements Cookbook
=====================

Sizing
------

Infrastructure
--------------
This section describes what changes you'll need to make to a your CI system to
add an ironic job.

jenkins changes
###############

nodepool changes
################

neutron changes
###############

pre-test hook
#############

cleanup hook
############

Ironic
------


Hardware Pool Management
========================

Problem
-------
If you are using actual hardware as target machines for your CI testing
then the problem of two jobs trying to use the name target arises. If
you have one target machine and a maximum number of one jobs running on
your ironic pipeline at a time, then you won't run into this problem. However,
one target may not handle the load of ironic's daily patch submissions.

Solutions
---------

Zuul v3
#######

Molten Iron
###########
`molteniron <https://github.com/openstack/molteniron/>`_
is a tool that allows you to reserve hardware from a pool at the last minute
to use in your job. Once finished testing, you can unreserve the hardware
making it available for the next test job.

Tips and Tricks
===============

Optimize Run Time
-----------------
Image Server
############

Other References
----------------

