.. _faq:

==========================================
Developer FAQ (frequently asked questions)
==========================================

Here are some answers to frequently-asked questions from IRC and
elsewhere.

.. contents::
    :local:
    :depth: 2


How do I…
=========

…create a migration script template?
------------------------------------

Using the ``alembic revision`` command, e.g::

  $ cd ironic/ironic/db/sqlalchemy
  $ alembic revision -m "create foo table"

For more information see the `alembic documentation`_.

.. _`alembic documentation`: https://alembic.readthedocs.org/en/latest/tutorial.html#create-a-migration-script
