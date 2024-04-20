import typing as t
import enum

from dataclasses import dataclass
from tree_sitter import Language, Parser, Tree, Node

from ._aidl import language as aidl_lang
from ._java import language as java_lang

AIDL = Language(aidl_lang(), "aidl")
JAVA = Language(java_lang(), "java")


# --- constants ---
class Constants:
    METHOD_DECL = "method_declaration"
    CONSTUCTOR_DECL = "constructor_declaration"
    FIELD_DECL = "field_declaration"
    IMPORT_DECL = "import_declaration"
    CLASS_DECL = "class_declaration"
    FORMAL_PARAMETERS = "formal_parameters"
    FORMAL_PARAMETER = "formal_parameter"
    INTERFACE_DECL = "interface_declaration"
    CONSTUCTOR_BODY = "constructor_body"
    BLOCK = "block"
    IDENTIFIER = "identifier"
    LOCAL_VAR_DECL = "local_variable_declaration"

    # statement types
    EXPR_STATEMENT = "expression_statement"
    RETURN_STATMENT = "return_statement"
    IF_STATEMENT = "if_statement"

    # expression types
    OBJ_CREATION_EXPR = "object_creation_expression"
    ASSIGNMENT_EXPR = "assignment_expression"
    PARENTHESIZED_EXPR = "parenthesized_expression"
    BINARY_EXPR = "binary_expression"

    METHOD_CALL = "method_invocation"
    FIELD_ACCESS = "field_access"

    AIDL_PARCELABLE_DEF = "parcelable_definition"
    AIDL_METHOD_DECL = "binder_method_declaration"
    AIDL_FORMAL_PARAMETERS = "binder_formal_parameters"
    AIDL_FORMAL_PARAMETER = "binder_formal_parameter"


# --- public API ---


def parse_aidl(text: bytes) -> Tree:
    """
    Parses the given AIDL file and returns the AST.
    """
    parser = Parser()
    parser.set_language(AIDL)
    return parser.parse(text)


def parse_java(text: bytes) -> Tree:
    """
    Parses the given Java file and returns the AST.
    """
    parser = Parser()
    parser.set_language(JAVA)
    return parser.parse(text)


class Type(enum.Enum):
    """The type of a unit."""

    PARCELABLE = 0
    """A parcelable class (directly from an AIDL file)."""

    PARCELABLE_JAVA = 1
    """A parcelable class, which was loaded from a Java file."""

    BINDER = 2  # conforms to an interface
    """An interface definition (binder) from an AIDL file."""

    SPECIAL = 3  # unused
    UNDEFINED = 4  # unused


@dataclass(slots=True)
class Unit:
    """
    A compilation unit describes either a Java class, a binder
    interface or a parcelable declaration.
    """

    package: str
    """The package name of this unit"""

    imports: t.List[str]
    """The imports of this unit (static imports omitted)"""

    name: str
    """The name of this unit"""

    type: Type
    """The type of this unit"""

    body: Node
    """The unit's AST

    Note that this value may be a `ParcelableDef` of `BinderDef`
    if imported through a JSON file.
    """


def get_imports(program: Node, lang: Language) -> t.List[str]:
    """
    Returns the imports of the given program.
    """
    query = lang.query(f"({Constants.IMPORT_DECL}) @type")
    results = query.captures(program)
    imports = []
    for import_declaration, _ in results:
        path = import_declaration.child(1).text.decode()
        if path == "static":
            continue
        if len(import_declaration.children) == 5:  # includes asterisk
            path = f"{path}.*"
        imports.append(path)
    return imports


def get_package(program: Node, lang: Language) -> t.Optional[str]:
    """
    Returns the package of the given program.
    """
    query = lang.query("(package_declaration) @type")
    results = query.captures(program)
    if len(results) == 0:
        return None
    package_declaration, _ = results[0]
    return package_declaration.child(1).text.decode()


def get_class_by_name(program: Node, name: str, lang: Language) -> t.Optional[Node]:
    """
    Returns the class node in the given program.
    """
    query = lang.query(f"({Constants.CLASS_DECL}) @{name}")
    results = query.captures(program)
    for decl, _ in results:
        if decl.child_by_field_name("name").text.decode() == name:
            return decl
    return None


def get_method_by_name(program: Node, name: str, lang: Language) -> t.Optional[Node]:
    """
    Returns the method node in the given program.
    """
    query = lang.query(f"({Constants.METHOD_DECL}) @{name}")
    results = query.captures(program)
    for method_declaration, _ in results:
        if method_declaration.child_by_field_name("name").text.decode() == name:
            return method_declaration
    return None


def get_parcelables(program: Node) -> t.List[Node]:
    """
    Returns the parcelable nodes in the given program.
    """
    query = AIDL.query(f"({Constants.AIDL_PARCELABLE_DEF}) @type")
    results = query.captures(program)
    return [result[0] for result in results]


def get_binder_methods(program: Node) -> t.Dict[str, Node]:
    """
    Returns the binder method nodes in the given program.
    """
    return get_methods(program, AIDL, Constants.AIDL_METHOD_DECL)


def get_parameters(
    program: Node, lang: Language, param_type: t.Optional[str] = None
) -> t.Dict[str, Node]:
    """
    Returns the parameter nodes in the given program.
    """
    query = lang.query(f"({param_type or Constants.FORMAL_PARAMETERS}) @type")
    results = query.captures(program)
    parameters = {}
    for formal_parameters, _ in results:
        for parameter in formal_parameters.named_children:
            parameters[parameter.child_by_field_name("name").text.decode()] = parameter
    return parameters


def get_methods(
    program: Node,
    lang: Language,
    method_type: t.Optional[str] = None,
    scope: t.Optional[Node] = None,
) -> t.Dict[str, Node]:
    """
    Returns the method nodes in the given program.
    """
    query = lang.query(f"({method_type or Constants.METHOD_DECL}) @type")
    results = query.captures(program)
    return {
        md.child_by_field_name("name").text.decode(): md
        for md, _ in results
        if (scope is None or md.parent == scope)
    }


def get_method_return_type(program: Node) -> str:
    """Returns the return type of a method node"""
    return program.child_by_field_name("type").text.decode()


def get_parameter_modifier(program: Node) -> str:
    """Returns the modifier of a parameter node"""
    param_type = program.child(0).type
    if param_type in ("in", "out", "inout"):
        return param_type
    return "in"


# --- extra model helpers ---
# @dataclass(frozen=True, init=False)
# class IMethodInvocation:
#     qualifier: str
#     name: str
#     arguments: t.List[Node]
