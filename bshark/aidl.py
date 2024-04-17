import typing as t

from dataclasses import dataclass
from tree_sitter import Language, Parser, Tree, Node, Query

from ._aidl import language as aidl_lang
from ._java import language as java_lang

AIDL = Language(aidl_lang(), "aidl")
JAVA = Language(java_lang(), "java")


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

    body: Node
    """The unit's AST"""


def get_imports(program: Node, lang: Language) -> t.List[str]:
    """
    Returns the imports of the given program.
    """
    query = lang.query("(import_declaration) @type")
    results = query.captures(program)
    imports = []
    for import_declaration, _ in results:
        path = import_declaration.child(1).text.decode()
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
    query = lang.query(f"(class_declaration) @{name}")
    results = query.captures(program)
    if len(results) == 0:
        return None
    class_declaration, _ = results[0]
    return class_declaration


def get_method_by_name(program: Node, name: str, lang: Language) -> t.Optional[Node]:
    """
    Returns the method node in the given program.
    """
    query = lang.query(f"(method_declaration) @{name}")
    results = query.captures(program)
    if len(results) == 0:
        return None
    method_declaration, _ = results[0]
    return method_declaration


def get_field_by_name(program: Node, name: str, lang: Language) -> t.Optional[Node]:
    """
    Returns the field node in the given program.
    """
    query = lang.query(f"(field_declaration) @{name}")
    results = query.captures(program)
    if len(results) == 0:
        return None
    field_declaration, _ = results[0]
    return field_declaration

