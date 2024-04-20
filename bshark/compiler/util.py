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


def get_declaring_class(qname: QName) -> QName:
    parts = qname.split(".")
    classes = len(list(filter(lambda x: x[0].isupper(), parts)))
    idx = classes - 1
    return ".".join(parts[:-idx]) if idx > 0 else qname


def to_qname(unit: Unit) -> QName:
    """Get the qualified name of a unit."""
    ty = unit.types[0]
    if isinstance(ty, ClassDef):
        return ty.qname

    return ".".join([unit.package.name, ty.name])


# --- internal helpers ---
def filteraidl(files):
    return filter(lambda f: f.endswith(FULL_AIDL_EXT), files)
