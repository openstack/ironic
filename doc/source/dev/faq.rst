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
