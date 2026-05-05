// NOTE(clif): This grammar is used by lark to generate the parser found in
// kernel_parameter_parser.py
//
// The following assumes your current working directory is the same as this
// grammar file and the lark python library is available. Check the existing
// generated parser to find the lark
// version used.
//
// Use this command to regenerate the parser:
//
// $ python -m lark.tools.standalone grammar.g > kernel_parameter_parser.py
//
// The generated file (kernel_parameter_parser.py) will note at the beginning
// of the file which version of lark was used to generate it. Additionally
// note that lark requires python >= 3.8. Which means the stand-alone parser
// *should* be fine for any recent-ish version of Ironic.
//
// NOTE(clif): The generated parser has some calls to pickle which trip
// Bandit's B301 test. If you regenerate the parser you will need to mark
// Those lines as # noqa B301
// If for some reason we do end up using lark's cache or save/load()
// functionality then we'll have to revisit this decision.

?start: kernel_command_line

kernel_command_line: parameter_list

parameter_list: parameter?(" "+ parameter)*

parameter: key
         | key_value_pair

key_value_pair: key"="value

key: /[A-Za-z0-9_\-\.]+/

value: bare_value
     | quoted_value

quoted_value: "\"" value_with_spaces "\""

bare_value: /[\!\#-\\.0-9:-\@A-Za-z\[-~]+/

value_with_spaces: /[\!\#-\\.0-9:-\@A-Za-z\[-~ ]+/
