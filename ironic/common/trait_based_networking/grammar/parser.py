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

import ironic.common.trait_based_networking.base as tbn_base

import lark

FILTER_EXPRESSION_GRAMMAR = r"""
filter_expression: single_expression
                 | compound_expression
                 | paren_expression
                 | function_expression

function_expression: function

single_expression: variable_name comparator string_literal

compound_expression: filter_expression ( boolean_operator filter_expression )+

paren_expression: "(" filter_expression ")"

boolean_operator: "&&" -> op_and
                | "||" -> op_or

comparator: "==" -> equality
          | "!=" -> inequality
          | ">=" -> gt_or_eq
          | ">"  -> gt
          | "<=" -> lt_or_eq
          | "<"  -> lt
          | "=~" -> prefix_match

function: "port.is_port"      -> port_is_port
        | "port.is_portgroup" -> port_is_portgroup

string_literal: /\'[A-Za-z0-9_\-\.]*\'/
variable_name: /[a-z]+\.[a-z\_]+/

%import common.WS
%ignore WS
"""

FILTER_EXPRESSION_GRAMMAR_START_RULE = 'filter_expression'

FilterExpressionParser = lark.Lark(FILTER_EXPRESSION_GRAMMAR,
                                   start=FILTER_EXPRESSION_GRAMMAR_START_RULE)


class FilterExpressionTransformer(lark.Transformer):
    def op_and(self, items):
        return tbn_base.Operator.AND

    def op_or(self, items):
        return tbn_base.Operator.OR

    def equality(self, items):
        return tbn_base.Comparator.EQUALITY

    def inequality(self, items):
        return tbn_base.Comparator.INEQUALITY

    def gt_or_eq(self, items):
        return tbn_base.Comparator.GT_OR_EQ

    def gt(self, items):
        return tbn_base.Comparator.GT

    def lt_or_eq(self, items):
        return tbn_base.Comparator.LT_OR_EQ

    def lt(self, items):
        return tbn_base.Comparator.LT

    def prefix_match(self, items):
        return tbn_base.Comparator.PREFIX_MATCH

    def single_expression(self, items):
        return tbn_base.SingleExpression(items[0], items[1], items[2])

    def compound_expression(self, items):
        return tbn_base.CompoundExpression(items[0], items[1], items[2])

    def paren_expression(self, items):
        return tbn_base.ParenExpression(items[0])

    def filter_expression(self, items):
        return tbn_base.FilterExpression(items[0])

    def port_is_port(self, items):
        return tbn_base.Variables.PORT_IS_PORT

    def port_is_portgroup(self, items):
        return tbn_base.Variables.PORT_IS_PORTGROUP

    def function_expression(self, items):
        return tbn_base.FunctionExpression(items[0])

    def variable_name(self, items):
        token = items[0]
        return tbn_base.Variables(token.value)

    def string_literal(self, items):
        token = items[0]
        # Strip ' characters from literal.
        return token.value[1:-1]
