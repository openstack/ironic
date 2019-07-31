.. _adding-new-job:

================
Adding a new Job
================

Are you familiar with Zuul?
===========================

Before start trying to figure out how Zuul works, take some time and read
about `Zuul Config <zuul_config_>`_ and the
`Zuul Best Practices <zuul_best_practices_>`_.

.. _zuul_config: https://zuul-ci.org/docs/zuul/user/config.html
.. _zuul_best_practices: https://docs.openstack.org/infra/manual/creators.html#zuul-best-practices

Where can I find the existing jobs?
===================================

The jobs for the Ironic project are defined under the zuul.d_ folder in the
root directory, that contains three files, whose function is described
below.

* ironic-jobs.yaml_: Contains the configuration of each Ironic Job converted
  to Zuul v3.

* legacy-ironic-jobs.yaml_: Contains the configuration of each Ironic Job that
  haven't been converted to Zuul v3 yet.

* project.yaml_: Contains the jobs that will run during check and gate phase.


.. _zuul.d: https://opendev.org/openstack/ironic/src/branch/master/zuul.d
.. _ironic-jobs.yaml: https://opendev.org/openstack/ironic/src/branch/master/zuul.d/ironic-jobs.yaml
.. _legacy-ironic-jobs.yaml: https://opendev.org/openstack/ironic/src/branch/master/zuul.d/legacy-ironic-jobs.yaml
.. _project.yaml: https://opendev.org/openstack/ironic/src/branch/master/zuul.d/project.yaml


Create a new Job
================

Identify among the existing jobs the one that most closely resembles the
scenario you want to test, the existing job will be used as `parent` in your
job definition.
Now you will only need to either overwrite or add variables to your job
definition under the `vars` section to represent the desired scenario.

The code block below shows the minimal structure of a new job definition that
you need to add to ironic-jobs.yaml_.

.. code-block:: yaml

   - job:
       name: <name of the new job>
       description: <what your job does>
       parent: <Job that already exists>
       vars:
         <var1>: <new value>

After having the definition of your new job you just need to add the job name
to the project.yaml_ under `check` and `gate`. Only jobs that are voting
should be in the `gate` section.

.. code-block:: yaml

   - project:
       check:
         jobs:
           - <name of the new job>
       gate:
         queue: ironic
         jobs:
           - <name of the new job>
