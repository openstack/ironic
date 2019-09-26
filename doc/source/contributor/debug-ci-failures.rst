.. _debug-ci-failures:

=====================
Debugging CI failures
=====================


If you see `FAILURE` in one or more jobs for your patch please don't panic.
This guide may help you to find the initial reason for the failure.
When clicking in the failed job you will be redirect to the Zuul web page that
contains all the information about the job build.


Zuul Web Page
=============

The page has three tabs: `Summary`, `Logs` and `Console`.

* Summary: Contains overall information about the build of the job, if the job
  build failed it will contain a general output of the failure.

* Logs:  Contains all configurations and log files about all services that
  were used in the job. This will give you an overall idea of the failures and
  you can identify services that may be involved. The `job-output` file can
  give an overall idea of the failures and what services may be involved.

* Console: Contains all the playbooks that were executed, by clicking in the
  arrow before each playbook name you can find the roles and commands that were
  executed.

