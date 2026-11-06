.. _jobs-description:

================
Jobs description
================

Descriptions for Ironic CI jobs are maintained in the ``description`` field of
each Zuul job definition. They are displayed in the `Ironic jobs in Zuul`_.

When adding or changing a CI job, update its description in the corresponding
Zuul YAML file. Describe the job's purpose and what it validates; for image
jobs, also clarify whether they publish artifacts or only build them for
validation.

.. _Ironic jobs in Zuul: https://zuul.opendev.org/t/openstack/jobs?project=openstack%2Fironic
