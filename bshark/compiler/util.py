# MIT License
#
# Copyright (c) 2024 MatrixEditor
#
# Permission is hereby granted, free of charge, to any person obtaining a copy
# of this software and associated documentation files (the "Software"), to deal
# in the Software without restriction, including without limitation the rights
# to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
# copies of the Software, and to permit persons to whom the Software is
# furnished to do so, subject to the following conditions:
#
# The above copyright notice and this permission notice shall be included in all
# copies or substantial portions of the Software.
#
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
# IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
# FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
# AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
# LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
# OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
# SOFTWARE.
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
