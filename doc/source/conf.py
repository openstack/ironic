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

# -- General configuration ----------------------------------------------------

# Add any Sphinx extension module names here, as strings. They can be
# extensions coming with Sphinx (named 'sphinx.ext.*') or your custom ones.
extensions = ['sphinx.ext.autodoc',
              'sphinx.ext.viewcode',
              'sphinxcontrib.httpdomain',
              'sphinxcontrib.pecanwsme.rest',
              'sphinxcontrib.seqdiag',
              'wsmeext.sphinxext',
              'oslo_config.sphinxext',
              'oslo_config.sphinxconfiggen',
              'oslo_policy.sphinxext',
              'oslo_policy.sphinxpolicygen',
              ]

try:
    import openstackdocstheme
    extensions.append('openstackdocstheme')
except ImportError:
    openstackdocstheme = None

repository_name = 'openstack/ironic'
bug_project = 'ironic'
bug_tag = ''
html_last_updated_fmt = '%Y-%m-%d %H:%M'

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
project = u'Ironic'
copyright = u'OpenStack Foundation'

config_generator_config_file = '../../tools/config/ironic-config-generator.conf'
sample_config_basename = '_static/ironic'

policy_generator_config_file = '../../tools/policy/ironic-policy-generator.conf'
sample_policy_basename = '_static/ironic'

# The version info for the project you're documenting, acts as replacement for
# |version| and |release|, also used in various other places throughout the
# built documents.
#
# The short X.Y version.
from ironic import version as ironic_version
# The full version, including alpha/beta/rc tags.
release = ironic_version.version_info.release_string()
# The short X.Y version.
version = ironic_version.version_info.version_string()

# A list of ignored prefixes for module index sorting.
modindex_common_prefix = ['ironic.']

# If true, '()' will be appended to :func: etc. cross-reference text.
add_function_parentheses = True

# If true, the current module name will be prepended to all description
# unit titles (such as .. function::).
add_module_names = True

# The name of the Pygments (syntax highlighting) style to use.
pygments_style = 'sphinx'

# A list of glob-style patterns that should be excluded when looking for
# source files. They are matched against the source file names relative to the
# source directory, using slashes as directory separators on all platforms.
exclude_patterns = ['api/ironic_tempest_plugin.*']

# Ignore the following warning: WARNING: while setting up extension
# wsmeext.sphinxext: directive 'autoattribute' is already registered,
# it will be overridden.
suppress_warnings = [ 'app.add_directive']

# -- Options for HTML output --------------------------------------------------

# The theme to use for HTML and HTML Help pages.  Major themes that come with
# Sphinx are currently 'default' and 'sphinxdoc'.
if openstackdocstheme is not None:
    html_theme = 'openstackdocs'
else:
    html_theme = 'default'

# Output file base name for HTML help builder.
htmlhelp_basename = '%sdoc' % project


# Grouping the document tree into LaTeX files. List of tuples
# (source start file, target name, title, author, documentclass
# [howto/manual]).
latex_documents = [
    (
        'index',
        '%s.tex' % project,
        u'%s Documentation' % project,
        u'OpenStack Foundation',
        'manual'
    ),
]

# -- Options for seqdiag ------------------------------------------------------

seqdiag_html_image_format = "SVG"
