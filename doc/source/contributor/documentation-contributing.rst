===============================
Contributing to Ironic Docs
===============================

This guide will help you get started with contributing to Ironic docs, whether you are fixing a typo or writing a new section.

Where the Docs Live
---------------------

Ironic has multiple documentation sources located in different directories of the `openstack/ironic
repository <https://opendev.org/openstack/ironic>`_.

- ``doc/source/`` – Primary Ironic documentation
- ``api-ref/source/`` – API Reference (https://docs.openstack.org/api-ref/baremetal/)
- ``releasenotes/`` – Release notes for Ironic

How to Get Started
--------------------

Clone the repository locally and create a new branch for your work.

For setup instructions, including creating a ``Gerrit account``
refer to the `Developer's Guide <https://docs.opendev.org/opendev/infra-manual/latest/developers.html>`_.

Make and Preview Documentation Changes
----------------------------------------

You can preview your documentation changes locally using the following command:

.. code-block:: bash

   tox -e docs

This will build the HTML version in ``doc/build/html/``.
Open ``index.html`` in your browser to view your updates.

.. note:: If you have created a new file, make sure to include its path in the documentation table of contents.

To do this, edit ``doc/source/index.rst`` (or another relevant .rst file) and
add the relative path of your new file to the ``.. toctree::`` directive. For example:

.. code-block:: rst

   .. toctree::
      :maxdepth: 2

      contributor/doc_contributing

To open the generated HTML:

**Option 1 – Open the HTML file directly:**

- On Linux:

.. code-block:: bash

   xdg-open doc/build/html/index.html

- On macOS:

.. code-block:: bash

   open doc/build/html/index.html

- On Windows:

Navigate to the ``doc/build/html/`` folder and double-click ``index.html``.

**Option 2 – Start a local web server (Cross-platform):**

.. code-block:: bash

   cd doc/build/html
   python -m http.server

Then navigate to URL.

Lint and Check Your Work
------------------------------

Before submitting, check your documentation and code formatting with:

.. code-block:: bash

   tox -e pep8

This ensures ``.rst`` files follow style guidelines and catch common mistakes.

How to Submit Your Changes
-----------------------------

After confirming your changes are correct, commit them with a clear message and submit for review with:

   .. code-block:: bash

      git review

Your patch will appear in the OpenStack Gerrit system for feedback and approval.

Writing Style and Guidelines
-----------------------------

* Follow OpenStack's `documentation <https://docs.openstack.org/doc-contrib-guide/>`_ style guide.
* Keep language clear, inclusive, and technical.
* Avoid passive voice and ambiguous words.
* Use reStructuredText (``.rst``) syntax.

Asking for Help
-------------------

If you are stuck, don’t hesitate to reach out to the
`ironic community <https://docs.openstack.org/ironic/latest/contributor/community.html>`_.


Maintainers and review team information can be found in the ``doc/OWNERS`` file.
