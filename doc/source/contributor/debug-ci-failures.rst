.. _debug-ci-failures:

=====================
Debugging CI failures
=====================


If you see `FAILURE` in one or more jobs for your patch please don't panic.
This guide may help you to find the initial reason for the failure.
When clicking in the failed job you will be redirect to a page that
contains all the logs and configurations used to run the job.


Using Ara Report
================

The `ara-report` folder will redirect you to a UI where you can see all the
playbooks that were used to execute the job, and you will be able to find the
playbook that failed. Click on the `Tasks` button for the playbook that failed
and then click on the `Status` button for the task that has failed.

You will be able to see what command was being executed and you can test
locally to see if you can reproduce the failure locally.


Looking at logs
===============

If you want to go more deep in your investigation you can look at the
`job-output` file, it will give you an overall idea of the failures and you
can identify services that may be involved. Under `controller/logs` you can
find the the configuration and logs of those services.
