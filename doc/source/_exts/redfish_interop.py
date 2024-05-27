#    Licensed under the Apache License, Version 2.0 (the "License"); you may
#    not use this file except in compliance with the License. You may obtain
#    a copy of the License at
#
#         http://www.apache.org/licenses/LICENSE-2.0
#
#    Unless required by applicable law or agreed to in writing, software
#    distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
#    WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
#    License for the specific language governing permissions and limitations
#    under the License.

import json
import os

from sphinx.application import Sphinx

__version__ = "1.0.0"


# Data model #


class Entity:
    """Represents an entity in the profile."""

    def __init__(self, name, src):
        self.name = name
        self.src = src
        self.purpose = src.get('Purpose', '')
        self.writable = src.get('WriteRequirement') == 'Mandatory'
        self.required = (src.get('ReadRequirement') in ('Mandatory', None)
                         or self.writable)


class ActionParameter(Entity):
    """Represents a parameter in an Action."""

    def __init__(self, name, src):
        super().__init__(name, src)
        self.required_values = src.get('ParameterValues') or []
        self.recommended_values = src.get('RecommendedValues') or []


class Action(Entity):
    """Represents an action on a resource."""

    def __init__(self, name, src):
        super().__init__(name, src)
        self.parameters = {
            name: ActionParameter(name, value)
            for name, value in src.get('Parameters', {}).items()
        }


class Resource(Entity):
    """Represents any resource in the profile.

    Both top-level resources and nested fields are represented by this class
    (but actions are not).
    """

    def __init__(self, name, src):
        super().__init__(name, src)
        self.min_support_values = src.get('MinSupportValues')
        self.properties = {
            name: Resource(name, value)
            for name, value in src.get('PropertyRequirements', {}).items()
        }
        self.actions = {
            name: Action(name, value)
            for name, value in src.get('ActionRequirements', {}).items()
        }
        self.link_to = (src['Values'][0]
                        if src.get('Comparison') == 'LinkToResource'
                        else None)


# Rendering #

LEVELS = {0: '=', 1: '-', 2: '~', 3: '^'}
INDENT = ' ' * 4


class NestedWriter:
    """A writer that is nested with indentations."""

    def __init__(self, dest, level=0):
        self.dest = dest
        self.level = level

    def text(self, text):
        print(INDENT * self.level + text, file=self.dest)

    def para(self, text):
        self.text(text)
        print(file=self.dest)

    def _nested_common(self, res):
        required = " **[required]**" if res.required else ""
        writable = " **[writable]**" if res.writable else ""
        self.text(f"``{res.name}``{required}{writable}")
        nested = NestedWriter(self.dest, self.level + 1)
        if res.purpose:
            nested.para(res.purpose)
        return nested

    def action(self, res):
        nested = self._nested_common(res)
        for prop in res.parameters.values():
            nested.action_parameter(prop)
        print(file=self.dest)

    def action_parameter(self, res):
        self._nested_common(res)
        print(file=self.dest)

    def resource(self, res):
        nested = self._nested_common(res)
        for prop in res.properties.values():
            nested.resource(prop)
        if res.link_to:
            # NOTE(dtantsur): this is a bit hacky, but we don't have
            # definitions for all possible collections.
            split = res.link_to.split('Collection')
            if len(split) > 1:
                nested.text("Link to a collection of "
                            f":ref:`Redfish-{split[0]}` resources.")
            else:
                nested.text(f"Link to a :ref:`Redfish-{res.link_to}` "
                            "resource.")

        print(file=self.dest)


class Writer(NestedWriter):

    def __init__(self, dest):
        super().__init__(dest)

    def title(self, text, level=1):
        print(text, file=self.dest)
        print(LEVELS[level] * len(text), file=self.dest)

    def top_level(self, res):
        required = " **[required]**" if res.required else ""
        self.para(f".. _Redfish-{res.name}:")
        self.title(f"{res.name}")
        self.para(f"{res.purpose}{required}")
        if res.properties:
            self.title("Properties", level=2)
            for name, prop in res.properties.items():
                self.resource(prop)
        if res.actions:
            self.title("Actions", level=2)
            for name, act in res.actions.items():
                self.action(act)


def builder_inited(app: Sphinx):
    source = os.path.join(app.srcdir, app.config.redfish_interop_source)
    with open(source) as fp:
        profile = json.load(fp)
    fname = os.path.basename(source).replace('json', 'rst')
    dstdir = os.path.join(app.srcdir, app.config.redfish_interop_output_dir)
    with open(os.path.join(dstdir, fname), 'wt') as dest:
        w = Writer(dest)
        w.title(f"{profile['ProfileName']} {profile['ProfileVersion']}", 0)
        w.para(profile['Purpose'])

        try:
            for name, value in sorted(
                (name, value)
                for name, value in profile['Resources'].items()
            ):
                w.top_level(Resource(name, value))
        except Exception:
            import traceback
            traceback.print_exc()
            raise


def setup(app: Sphinx):
    app.connect('builder-inited', builder_inited)
    app.add_config_value('redfish_interop_source', None, 'env', [str])
    app.add_config_value('redfish_interop_output_dir', None, 'env', [str])
    return {'version': __version__}
