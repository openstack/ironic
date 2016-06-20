.. _faq:

==========================================
Developer FAQ (frequently asked questions)
==========================================

Here are some answers to frequently-asked questions from IRC and
elsewhere.

.. contents::
    :local:
    :depth: 2


How do I...
===========

...create a migration script template?
--------------------------------------

Using the ``alembic revision`` command, e.g::

  $ cd ironic/ironic/db/sqlalchemy
  $ alembic revision -m "create foo table"

For more information see the `alembic documentation`_.

.. _`alembic documentation`: https://alembic.readthedocs.org/en/latest/tutorial.html#create-a-migration-script

...know if a release note is needed for my change?
--------------------------------------------------

`Reno documentation`_ contains a description of what can be added to each
section of a release note. If, after reading this, you're still unsure about
whether to add a release note for your change or not, keep in mind that it is
intended to contain information for deployers, so changes to unit tests or
documentation are unlikely to require one.

...create a new release note?
-----------------------------

By running ``reno`` command via tox, e.g::

  $ tox -e venv -- reno new version-foo
    venv create: /home/foo/ironic/.tox/venv
    venv installdeps: -r/home/foo/ironic/test-requirements.txt
    venv develop-inst: /home/foo/ironic
    venv runtests: PYTHONHASHSEED='0'
    venv runtests: commands[0] | reno new version-foo
    Created new notes file in releasenotes/notes/version-foo-ecb3875dc1cbf6d9.yaml
      venv: commands succeeded
      congratulations :)

  $ git status
    On branch test
    Untracked files:
      (use "git add <file>..." to include in what will be committed)

      releasenotes/notes/version-foo-ecb3875dc1cbf6d9.yaml

Then edit the result file.

For more information see the `reno documentation`_.

.. _`reno documentation`: http://docs.openstack.org/developer/reno/usage.html

...get a decision on something?
-------------------------------

You have an issue and would like a decision to be made. First, make sure
that the issue hasn't already been addressed, by looking at documentation,
bugs, specifications, or asking. Information and links can be found on the
`Ironic wiki`_ page.

There are several ways to solicit comments and opinions:

* bringing it up at the `weekly Ironic meeting`_
* bringing it up on IRC_
* bringing it up on the `mailing list`_ (add "[Ironic]" to the Subject of the
  email)

If there are enough core folks at the weekly meeting, after discussing an
issue, voting could happen and a decision could be made.
The problem with IRC or the weekly meeting is that feedback will only
come from the people that are actually present.

To inform (and solicit feedback from) more people about an issue,
the preferred process is:

#. bring it up on the mailing list
#. after some period of time has elapsed (and depending on the
   thread activity), someone should propose a solution via gerrit.
   (E.g. the person that started the thread if no one else steps up.)
   The proposal should be made in the git repository that is associated
   with the issue. (For instance, this decision process was proposed as a
   documentation patch to the ironic repository.)
#. In the email thread, don't forget to provide a link to the proposed patch!
#. The discussion then moves to the proposed patch. If this is a big
   decision, we could declare that some percentage of the cores should
   vote on it before landing it.

(This process was suggested in an email thread about
`process for making decisions`_.)

.. _Ironic wiki: https://wiki.openstack.org/wiki/Ironic
.. _weekly Ironic meeting: https://wiki.openstack.org/wiki/Meetings/Ironic
.. _IRC: https://wiki.openstack.org/wiki/Ironic#IRC
.. _mailing list: http://lists.openstack.org/cgi-bin/mailman/listinfo/openstack-dev
.. _process for making decisions: http://lists.openstack.org/pipermail/openstack-dev/2016-May/095460.html
