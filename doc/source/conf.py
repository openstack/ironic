# -*- coding: utf-8 -*-
#  Licensed under the Apache License, Version 2.0 (the "License"); you may
#  not use this file except in compliance with the License. You may obtain
#  a copy of the License at
#
#       http://www.apache.org/licenses/LICENSE-2.0
#
#  Unless required by applicable law or agreed to in writing, software
#  distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
#  WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
#  License for the specific language governing permissions and limitations
#  under the License.

import os
import sys

import eventlet

# NOTE(dims): monkey patch subprocess to prevent failures in latest eventlet
# See https://github.com/eventlet/eventlet/issues/398
try:
    eventlet.monkey_patch(subprocess=True)
except TypeError:
    pass

# -- General configuration ----------------------------------------------------

# If extensions (or modules to document with autodoc) are in another directory,
# add these directories to sys.path here. If the directory is relative to the
# documentation root, use os.path.abspath to make it absolute, like shown here.
sys.path.insert(0, os.path.join(os.path.abspath('.'), '_exts'))

# Add any Sphinx extension module names here, as strings. They can be
# extensions coming with Sphinx (named 'sphinx.ext.*') or your custom ones.
extensions = ['sphinx.ext.viewcode',
              'sphinx.ext.graphviz',
              'sphinxcontrib.apidoc',
              'sphinxcontrib.rsvgconverter',
              'oslo_config.sphinxext',
              'oslo_config.sphinxconfiggen',
              'oslo_policy.sphinxext',
              'oslo_policy.sphinxpolicygen',
              'automated_steps',
              'openstackdocstheme',
              'web_api_docstring'
              ]

# sphinxcontrib.apidoc options
apidoc_module_dir = '../../ironic'
apidoc_output_dir = 'contributor/api'
apidoc_excluded_paths = [
    'db/sqlalchemy/alembic/env',
    'db/sqlalchemy/alembic/versions/*',
    'drivers/modules/ansible/playbooks*',
    'hacking',
    'tests',
]
apidoc_separate_modules = True

openstackdocs_repo_name = 'openstack/ironic'
openstackdocs_use_storyboard = False
openstackdocs_pdf_link = True
openstackdocs_projects = [
    'bifrost',
    'cinder',
    'glance',
    'ironic',
    'ironic-inspector',
    'ironic-lib',
    'ironic-neutron-agent',
    'ironic-python-agent',
    'ironic-ui',
    'keystone',
    'keystonemiddleware',
    'metalsmith',
    'networking-baremetal',
    'neutron',
    'nova',
    'oslo.messaging',
    'oslo.reports',
    'oslo.versionedobjects',
    'oslotest',
    'osprofiler',
    'os-traits',
    'python-ironicclient',
    'python-ironic-inspector-client',
    'python-openstackclient',
    'swift',
]

wsme_protocols = ['restjson']

# autodoc generation is a bit aggressive and a nuisance when doing heavy
# text edit cycles.
# execute "export SPHINX_DEBUG=1" in your terminal to disable

# Add any paths that contain templates here, relative to this directory.
templates_path = ['_templates']

# The suffix of source filenames.
source_suffix = '.rst'

# The master toctree document.
master_doc = 'index'

# General information about the project.
copyright = 'OpenStack Foundation'

config_generator_config_file = '../../tools/config/ironic-config-generator.conf'
sample_config_basename = '_static/ironic'

policy_generator_config_file = '../../tools/policy/ironic-policy-generator.conf'
sample_policy_basename = '_static/ironic'

# A list of ignored prefixes for module index sorting.
modindex_common_prefix = ['ironic.']

# If true, '()' will be appended to :func: etc. cross-reference text.
add_function_parentheses = True

# If true, the current module name will be prepended to all description
# unit titles (such as .. function::).
add_module_names = True

# The name of the Pygments (syntax highlighting) style to use.
pygments_style = 'native'

# A list of glob-style patterns that should be excluded when looking for
# source files. They are matched against the source file names relative to the
# source directory, using slashes as directory separators on all platforms.
exclude_patterns = ['api/ironic.drivers.modules.ansible.playbooks.*',
                    'api/ironic.tests.*']

# Ignore the following warning: WARNING: while setting up extension
# wsmeext.sphinxext: directive 'autoattribute' is already registered,
# it will be overridden.
suppress_warnings = ['app.add_directive']

# -- Options for HTML output --------------------------------------------------

# The theme to use for HTML and HTML Help pages.  Major themes that come with
# Sphinx are currently 'default' and 'sphinxdoc'.
html_theme = 'openstackdocs'

# Output file base name for HTML help builder.
htmlhelp_basename = 'Ironicdoc'

latex_use_xindy = False

# Grouping the document tree into LaTeX files. List of tuples
# (source start file, target name, title, author, documentclass
# [howto/manual]).
latex_documents = [
    (
        'index',
        'doc-ironic.tex',
        'Ironic Documentation',
        'OpenStack Foundation',
        'manual'
    ),
]

# Allow deeper levels of nesting for \begin...\end stanzas
latex_elements = {'maxlistdepth': 10}
