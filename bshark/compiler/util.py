import os
import aidl

from bshark import FULL_AIDL_EXT
from bshark.compiler.model import QName, RPath
from bshark.compiler.model import Unit, ClassDef


def get_qname(path: RPath) -> QName:
    """Get the qualified name of a relative path."""
    name = path.rsplit(".", 1)[0]
    return (
        name.strip("/")
        .replace("/", ".")
        .replace(FULL_AIDL_EXT, "")  # AIDL interfaces
        .replace(".java", "")  # Java source files
        .replace(".json", "")  # Serialized objects
    )


def get_rpath(name: QName) -> RPath:
    """Get the relative path of a qualified name."""
    return name.replace(".", "/") + FULL_AIDL_EXT


def get_package(qname: QName) -> QName:
    parts = qname.split(".")
    classes = len(list(filter(lambda x: x[0].isupper(), parts)))
    return ".".join(parts[:-classes])


def get_declaring_class(qname: QName) -> QName:
    parts = qname.split(".")
    classes = len(list(filter(lambda x: x[0].isupper(), parts)))
    return ".".join(parts[: -(classes - 1)])


def get_class_name(qname: QName) -> str:
    return qname.rsplit(".", 1)[1]


def to_qname(unit: Unit) -> QName:
    """Get the qualified name of a unit."""
    ty = unit.types[0]
    if isinstance(ty, ClassDef):
        return ty.qname

    return ".".join([unit.package.name, ty.name])


# --- internal helpers ---


def filterclasses(body):
    return filter(lambda t: isinstance(t, aidl.tree.ClassDeclaration), body)


def filtertypes(body):
    return filter(lambda t: isinstance(t, aidl.tree.TypeDeclaration), body)


def is_parcelable_unit(decl: aidl.tree.ClassDeclaration) -> bool:
    if not hasattr(decl, "implements"):
        return False
    return any(ty.name == "Parcelable" for ty in (decl.implements or []))


def filteraidl(files):
    return filter(lambda f: f.endswith(FULL_AIDL_EXT), files)
