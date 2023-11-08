Bug Deputy Guide
================

Ironic has a rotating bug deputy role with assigned responsibilities around
ensuring recurring project maintenance occurs, with a specific focus on bug
triage.

It is the intent that the time commitment of an upstream bug deputy be no more
than two to four hours a week on average.

Schedule
--------
Typically, a bug deputy will serve for a one week period, with the Ironic
meeting marking the beginning and end of the term.

A bug deputy schedule will be built at the beginning of the OpenStack release
cycle and populated by project volunteers. Contributors can select weeks to
volunteer for stints as bug deputy.

If there are insufficient volunteers, to cover a majority of weeks, the bug
deputy program will be cancelled.

Responsibilities
----------------

Bug Triage
^^^^^^^^^^
Triage bugs opened in any Ironic project.

All Ironic project bugtrackers, filtered and sorted for triage:

* `ironic <https://bugs.launchpad.net/ironic/+bugs?field.status%3Alist=NEW&field.status%3Alist=INCOMPLETE_WITH_RESPONSE&orderby=-id>`_
* `ironic-inspector <https://bugs.launchpad.net/ironic-inspector/+bugs?field.status%3Alist=NEW&field.status%3Alist=INCOMPLETE_WITH_RESPONSE&orderby=-id>`_
* `ironic-python-agent <https://bugs.launchpad.net/ironic-python-agent/+bugs?field.status%3Alist=NEW&field.status%3Alist=INCOMPLETE_WITH_RESPONSE&orderby=-id>`_
* `ironic-lib <https://bugs.launchpad.net/ironic-lib/+bugs?field.status%3Alist=NEW&field.status%3Alist=INCOMPLETE_WITH_RESPONSE&orderby=-id>`_
* `bifrost <https://bugs.launchpad.net/bifrost/+bugs?field.status%3Alist=NEW&field.status%3Alist=INCOMPLETE_WITH_RESPONSE&orderby=-id>`_
* `ironic-prometheus-exporter <https://bugs.launchpad.net/ironic-prometheus-exporter/+bugs?field.status%3Alist=NEW&field.status%3Alist=INCOMPLETE_WITH_RESPONSE&orderby=-id>`_
* `ironic-python-agent-builder <https://bugs.launchpad.net/ironic-python-agent-builder/+bugs?field.status%3Alist=NEW&field.status%3Alist=INCOMPLETE_WITH_RESPONSE&orderby=-id>`_
* `ironic-ui <https://bugs.launchpad.net/ironic-ui/+bugs?field.status%3Alist=NEW&field.status%3Alist=INCOMPLETE_WITH_RESPONSE&orderby=-id>`_
* `metalsmith <https://bugs.launchpad.net/metalsmith/+bugs?field.status%3Alist=NEW&field.status%3Alist=INCOMPLETE_WITH_RESPONSE&orderby=-id>`_
* `molteniron <https://bugs.launchpad.net/molteniron/+bugs?field.status%3Alist=NEW&field.status%3Alist=INCOMPLETE_WITH_RESPONSE&orderby=-id>`_
* `networking-baremetal <https://bugs.launchpad.net/networking-baremetal/+bugs?field.status%3Alist=NEW&field.status%3Alist=INCOMPLETE_WITH_RESPONSE&orderby=-id>`_
* `networking-generic-switch <https://bugs.launchpad.net/networking-generic-switch/+bugs?field.status%3Alist=NEW&field.status%3Alist=INCOMPLETE_WITH_RESPONSE&orderby=-id>`_
* `python-ironic-inspector-client <https://bugs.launchpad.net/python-ironic-inspector-client/+bugs?field.status%3Alist=NEW&field.status%3Alist=INCOMPLETE_WITH_RESPONSE&orderby=-id>`_
* `python-ironicclient <https://bugs.launchpad.net/python-ironicclient/+bugs?field.status%3Alist=NEW&field.status%3Alist=INCOMPLETE_WITH_RESPONSE&orderby=-id>`_
* `sushy <https://bugs.launchpad.net/sushy/+bugs?field.status%3Alist=NEW&field.status%3Alist=INCOMPLETE_WITH_RESPONSE&orderby=-id>`_
* `sushy-tools <https://bugs.launchpad.net/sushy-tools/+bugs?field.status%3Alist=NEW&field.status%3Alist=INCOMPLETE_WITH_RESPONSE&orderby=-id>`_
* `tenks <https://bugs.launchpad.net/tenks/+bugs?field.status%3Alist=NEW&field.status%3Alist=INCOMPLETE_WITH_RESPONSE&orderby=-id>`_
* `virtualbmc <https://bugs.launchpad.net/virtualbmc/+bugs?field.status%3Alist=NEW&field.status%3Alist=INCOMPLETE_WITH_RESPONSE&orderby=-id>`_

Bug Bash
^^^^^^^^
A bug bash is an informal, synchronous meeting to triage bugs. A bug deputy
runs one per week at a time and in a format convenient for them.

The selected time and venue for this should be announced on the mailing list
and at the Ironic meeting when the bug deputy position is handed over.

.. note::
  Bug bashes may be discontinued when the backlog of old, untriaged bugs have
  been worked through.

Review Periodic Stable CI Jobs
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
The bug deputy is responsible for reviewing the periodic stable CI jobs once
during their week and notifying the community if one fails for a new,
non-random reason. The bug deputy should also be prepared to help debug the
issue, but is ultimately only responsible for documenting it.

* `Periodic Zuul build failures for Ironic/IPA/Ironic-Prom-Exp/Bifrost <https://zuul.opendev.org/t/openstack/builds?project=openstack%2Fironic&project=openstack%2Fironic-python-agent&project=openstack%2Fironic-lib&project=openstack%2Fironic-prometheus-exporter&project=openstack%2Fbifrost&pipeline=periodic&pipeline=periodic-stable&result=FAILURE&result=RETRY_LIMIT&result=POST_FAILURE&result=ERROR&skip=0>`_
* `Periodic Zuul build failures for Ironic UI/NBM/NGS <https://zuul.opendev.org/t/openstack/builds?project=openstack%2Fnetworking-generic-switch&project=openstack%2Fironic-ui&project=openstack%2Fnetworking-baremetal&pipeline=periodic&pipeline=periodic-stable&result=FAILURE&result=RETRY_LIMIT&result=POST_FAILURE&result=ERROR&skip=0>`_
* `Periodic Zuul build failures for inspector-client/sushy/sushy-tools/vbmc/vpdu/ <https://zuul.opendev.org/t/openstack/builds?project=openstack%2Fpython-ironic-inspector-client&project=openstack%2Fsushy&project=openstack%2Fsushy-tools&project=openstack%2Fvirtualbmc&project=openstack%2Fvirtualpdu&pipeline=periodic&pipeline=periodic-stable&result=FAILURE&result=RETRY_LIMIT&result=POST_FAILURE&result=ERROR&skip=0>`_

As of this writing, no other projects under Ironic governance run periodic
jobs.

Weekly Report
^^^^^^^^^^^^^
Once a week, at the end of the bug deputy's term, they should deliver a report
to the Ironic meeting and the mailing list. This report should include any
concerning bugs or CI breakages, as well as any other issues that the bug
deputy feels the community needs to know about.

For contributors who do not wish to attend the weekly meeting, a small written
report in the meeting agenda is sufficient.
