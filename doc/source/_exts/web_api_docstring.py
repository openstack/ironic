# -*- coding: utf-8 -*-
#
# Licensed under the Apache License, Version 2.0 (the "License"); you may
# not use this file except in compliance with the License. You may obtain
# a copy of the License at
#
#    http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
# WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
# License for the specific language governing permissions and limitations
# under the License.

from http import HTTPStatus
import os
import re  # Stdlib

from docutils import nodes
from docutils.parsers.rst import Directive  # 3rd Party
from sphinx.util.docfields import GroupedField  # 3rd Party
import yaml  # 3rd party

from ironic.common import exception  # Application


def read_from_file(fpath):
    """Read the data in file given by fpath."""

    with open(fpath, 'r') as stream:
        yaml_data = yaml.load(stream, Loader=yaml.SafeLoader)
        return yaml_data


def split_str_to_field(input_str):
    """Split the input_str into 2 parts, the field name and field body.

    The split is based on this regex format: :field_name: field_body.
    """

    regex_pattern = "((^:{1}.*:{1})(.*))"
    field_name = None
    field_body = None

    if input_str is None:
        return field_name, field_body

    regex_output = re.match(regex_pattern, input_str)

    if regex_output is None and len(input_str) > 0:
        field_body = input_str.lstrip(' ')

    if regex_output is not None:
        field = regex_output.groups()
        field_name = field[1].strip(':')
        field_body = field[2].strip()

    return field_name, field_body


def parse_field_list(content):
    """Convert list of fields as strings, to a dictionary.

    This function takes a list of strings as input, each item being
    a :field_name: field_body combination, and converts it into a dictionary
    with the field names as keys, and field bodies as values.
    """

    field_list = {}  # dictionary to hold parsed input field list

    for c in content:
        if c is None:
            continue
        field_name, field_body = split_str_to_field(c)
        field_list[field_name] = field_body

    return field_list


def create_bullet_list(input_dict, input_build_env):
    """Convert input_dict into a sphinx representation of a bullet list."""

    grp_field = GroupedField('grp_field', label='title')
    bullet_list = nodes.paragraph()

    for field_name in input_dict:
        fbody_txt_node = nodes.Text(data=input_dict[field_name])
        tmp_field_node = grp_field.make_field(domain='py',
                                           types=nodes.field,
                                           items=[(field_name,
                                                   fbody_txt_node)],
                                           env=input_build_env)

        for c in tmp_field_node.children:
            if c.tagname == 'field_body':
                for ch in c.children:
                    bullet_list += ch

    return bullet_list


def create_table(table_title, table_contents):
    """Construct a docutils-based table (single row and column)."""

    table = nodes.table()
    tgroup = nodes.tgroup(cols=1)
    colspec = nodes.colspec(colwidth=1)
    tgroup.append(colspec)
    table += tgroup

    thead = nodes.thead()
    tgroup += thead

    row = nodes.row()
    entry = nodes.entry()
    entry += nodes.paragraph(text=table_title)
    row += entry

    thead.append(row)

    rows = []

    row = nodes.row()
    rows.append(row)

    entry = nodes.entry()
    entry += table_contents
    row += entry

    tbody = nodes.tbody()
    tbody.extend(rows)
    tgroup += tbody

    return table


def split_list(input_list):
    """Split input_list into three sub-lists.

    This function splits the input_list into three, one list containing the
    initial non-empty items, one list containing items appearing after the
    string 'Success' in input_list; and the other list containing items
    appearing after the string 'Failure' in input_list.
    """
    initial_flag = 1
    success_flag = 0
    failure_flag = 0

    initial_list = []
    success_list = []
    failure_list = []

    for c in input_list:
        if c == 'Success:':
            success_flag = 1
            failure_flag = 0
        elif c == 'Failure:':
            failure_flag = 1
            success_flag = 0
        elif c != '' and success_flag:
            success_list.append(c)
        elif c != '' and failure_flag:
            failure_list.append(c)
        elif c != '' and initial_flag:
            initial_list.append(c)

    return initial_list, success_list, failure_list


def process_list(input_list):
    """Combine fields split over multiple list items into one.

    This function expects to receive a field list as input,
    with each item in the list representing a line
    read from the document, as-is.

    It combines the field bodies split over multiple lines into
    one list item, making each field (name and body) one list item.
    It also removes extra whitespace which was used for indentation
    in input.
    """

    out_list = []

    # Convert list to string
    str1 = "".join(input_list)

    # Replace multiple spaces with one space
    str2 = re.sub(r'\s+', ' ', str1)

    regex_pattern = r'(:\S*.:)'

    # Split the string, based on field names
    list3 = re.split(regex_pattern, str2)

    # Remove empty items from the list
    list4 = list(filter(None, list3))

    # Append the field name and field body strings together
    for i in range(0, len(list4), 2):
        out_list.append(list4[i] + list4[i + 1])

    return out_list


def add_exception_info(failure_list):
    """Add exception information to fields.

    This function takes a list of fields (field name and field body)
    as an argument. If the field name is the name of an exception, it adds
    the exception code into the field name, and exception message into
    the field body.
    """

    failure_dict = {}

    # Add the exception code and message string
    for f in failure_list:
        field_name, field_body = split_str_to_field(f)
        exc_code = ""
        exc_msg = ""

        if (field_name is not None) and hasattr(exception, field_name):
            # Get the exception code and message string
            exc_class = getattr(exception, field_name)
            try:
                exc_code = exc_class.code
                exc_msg = exc_class._msg_fmt
            except AttributeError:
                pass

            # Add the exception's HTTP code and HTTP phrase
            # to the field name
            if isinstance(exc_code, HTTPStatus):
                field_name = (field_name
                             + " (HTTP "
                             + str(exc_code.value)
                             + " "
                             + exc_code.phrase
                             + ")")
            else:
                field_name = field_name + " (HTTP " + str(exc_code) + ")"

            # Add the exception's HTTP description to the field body
            field_body = exc_msg + " \n" + field_body

        # Add to dictionary if field name and field body exist
        if field_name is not None and field_body is not None:
            failure_dict[field_name] = field_body

    return failure_dict


class Parameters(Directive):
    """This class implements the Parameters Directive."""

    required_arguments = 1
    has_content = True

    def run(self):
        # Parse the input field list from the docstring, as a dictionary
        input_dict = {}
        input_dict = parse_field_list(self.content)

        # Read from yaml file
        param_file = self.arguments[0]
        cur_path = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        param_file_path = cur_path + '/' + param_file
        yaml_data = read_from_file(param_file_path)

        # Substitute the parameter descriptions with the yaml file descriptions
        for field_name in input_dict:
            old_field_body = input_dict[field_name]
            if old_field_body in yaml_data.keys():
                input_dict[field_name] = yaml_data[old_field_body]["description"]

        # Convert dictionary to bullet list format
        params_build_env = self.state.document.settings.env
        params_bullet_list = create_bullet_list(input_dict, params_build_env)

        # Create a table to display the final Parameters directive output
        params_table = create_table('Parameters', params_bullet_list)
        return [params_table]


class Return(Directive):
    """This class implements the Return Directive."""

    has_content = True

    def run(self):
        initial_list, success_list, failure_list = split_list(self.content)

        # Concatenate the field bodies split over multiple lines
        proc_fail_list = process_list(failure_list)

        # Add the exception code(s) and corresponding message string(s)
        failure_dict = {}
        failure_dict = add_exception_info(proc_fail_list)

        ret_table_contents = nodes.paragraph()
        if len(initial_list) > 0:
            for i in initial_list:
                initial_cont = nodes.Text(data=i)
                ret_table_contents += initial_cont

        if len(success_list) > 0:
            # Add heading 'Success:' to output
            success_heading = nodes.strong()
            success_heading += nodes.Text(data='Success:')
            ret_table_contents += success_heading

            # Add Success details to output
            success_detail = nodes.paragraph()
            for s in success_list:
                success_detail += nodes.Text(data=s)
            ret_table_contents += success_detail

        if len(proc_fail_list) > 0:
            # Add heading 'Failure:' to output
            failure_heading = nodes.strong()
            failure_heading += nodes.Text(data='Failure:')
            ret_table_contents += failure_heading

            # Add failure details to output
            ret_build_env = self.state.document.settings.env
            failure_detail = create_bullet_list(failure_dict, ret_build_env)
            ret_table_contents += failure_detail

        if len(initial_list) > 0 or len(success_list) > 0 or len(proc_fail_list) > 0:
            # Create a table to display the final Returns directive output
            ret_table = create_table('Returns', ret_table_contents)
            return [ret_table]
        else:
            return None


def setup(app):
    app.add_directive("parameters", Parameters)
    app.add_directive("return", Return)

    return {
        'version': '0.1',
        'parallel_read_safe': True,
        'parallel_write_safe': True,
    }
