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
import typing as t
import dataclasses as dc
import enum
import json

from bshark.aidl import Type, Unit

QName = str
"""Qualified class name.

This is a string of the form `package.ClassName`.
"""

RPath = str
"""Relative path.

This is a string of the form `path/to/file.ext`.
"""

ABSPath = str
"""Absolute path.

This is a string of the form `/src-root/path/to/file.ext`.
"""

QImport = str
"""Qualified import.

This is a string of the form `package.ClassName` with an optional wildcard
to import everything.
"""


class UnsupportedTypeError(TypeError):
    """A special exception used to mark unsupported types."""


class Primitive:
    """A storage class for all supported primitive types."""

    VALUES = {
        "double",
        "float",
        "long",
        "int",
        "short",
        "byte",
        "boolean",
        "char",
        "String",
        "Bundle",
    }


class Complex:
    """A storage class for all supported complex types."""

    VALUES = {
        "IBinder": "readStrongBinder",
        "android.os.IBinder": "readStrongBinder",
    }


# --- model definitions ---
@dc.dataclass(slots=True)
class FieldDef:
    """A simple parcelable field definition.

    It contains the name defined in the parcelable class and
    the corresponding call to the Parcel object.
    """

    name: str
    call: str

    def __hash__(self):
        return hash(self.name)


class Direction(enum.IntEnum):
    """The direction of an argument in a method call."""

    IN = 0
    OUT = 1
    INOUT = 2


@dc.dataclass(slots=True)
class ReturnDef:
    """A simple binder method return definition."""

    call: str

    def __hash__(self):
        return hash("")


@dc.dataclass(slots=True)
class ParameterDef:
    """A simple binder method parameter definition.

    It contains the name of the type and the corresponding
    call to the Parcel object as well as its direction.
    """

    name: str
    call: str
    direction: Direction = Direction.IN

    def __hash__(self):
        return hash(self.name)


@dc.dataclass(slots=True)
class MethodDef:
    """A simple parcelable method definition. (Binder method)

    Each method stores the source method name and the defined
    transaction code. Note that the transaction code may not
    match with the one in intercepted Transactions, since they
    are automatically inferred.

    The return type is optional and will be `None` to oneway
    methods.

    """

    name: str
    tc: int
    oneway: bool
    retval: t.Optional[t.List[ParameterDef | ReturnDef]]
    arguments: t.List[ParameterDef]

    def __hash__(self):
        return hash(self.name)


@dc.dataclass(slots=True)
class ImportDef:
    """A simple import statement definition.

    It contains the import path and the corresponding
    code unit, which will be `None` if the import failed.
    """

    qname: str
    file_type: Type = Type.UNDEFINED
    unit: t.Optional[Unit] = None

    @property
    def name(self) -> str:
        return self.qname.split(".")[-1]

    def __hash__(self):
        return hash(self.qname)

    def __eq__(self, other: str):
        return other in (self.name, self.qname)


@dc.dataclass(slots=True)
class ConditionDef:
    """A simple condition definition.

    A condition is a simple boolean expression that will be translated
    from an if-statement and transformed into a `readInt` call. All
    following field definitions will be placed here.
    """

    call: str
    check: str
    op: str
    consequence: t.List[FieldDef]
    alternative: t.List[FieldDef]


@dc.dataclass(slots=True)
class ClassDef:
    """A simple generic type definition."""

    qname: QName
    type: Type | str


@dc.dataclass(slots=True)
class ParcelableDef(ClassDef):
    """A simple parcelable definition."""

    fields: t.List[FieldDef | ConditionDef]


@dc.dataclass(slots=True)
class BinderDef(ClassDef):
    """A simple binder definition."""

    methods: t.List[MethodDef]


@dc.dataclass(slots=True)
class Stop:
    """A special stop definition.

    This class will be used to track special conditions within the
    Java code flow. It tells the parser to stop if this field is
    reached.
    """


class ImportDefList(list):
    """Internal class to store import definitions."""

    def get(self, name: QName) -> t.Optional[ImportDef]:
        """Returns the import definition with the given name."""
        for i in self:
            if i.name == name or (i.unit and i.unit.name == name):
                return i
        return None


# --- JSON conversion ---
def to_json(definition) -> str:
    """Converts the given definition to JSON."""
    obj = definition
    if isinstance(definition, t.Iterable):
        obj = [dc.asdict(x) for x in definition]
    else:
        obj = dc.asdict(definition)
    return json.dumps(obj, indent=2)


def from_json(json_str: str | dict) -> BinderDef | ParcelableDef:
    """Converts the given JSON string back to the definition."""
    if isinstance(json_str, str):
        obj = json.loads(json_str)
    else:
        obj = json_str

    if "type" not in obj:
        raise ValueError("No type specified")

    ty = Type[obj["type"]]
    match ty:
        case Type.BINDER:
            return _load_binder_from_json(obj)

        case Type.PARCELABLE | Type.PARCELABLE_JAVA:
            return _load_parcelable_from_json(obj)

    raise UnsupportedTypeError(f"Unsupported type: {ty}")


# --- internal ---
def _load_binder_from_json(doc: t.Dict[str, t.Any]) -> BinderDef:
    bdef = BinderDef(doc["qname"], Type.BINDER, [])
    for method in doc["methods"]:
        mdef = MethodDef(method["name"], method["tc"], method["oneway"], None, [])
        if method["retval"]:
            for rval in method["retval"]:
                mdef.retval = []
                if "name" in rval:
                    pdef = ParameterDef(
                        rval["name"], rval["call"], Direction(rval["direction"])
                    )
                    mdef.retval.append(pdef)
                else:
                    mdef.retval.append(ReturnDef(rval["call"]))
        for arg in method["arguments"]:
            mdef.arguments.append(
                ParameterDef(arg["name"], arg["call"], Direction(arg["direction"]))
            )
        bdef.methods.append(mdef)
    return bdef


def _load_field_from_json(doc: t.Dict[str, t.Any]) -> FieldDef | ConditionDef:
    if len(doc) == 0:
        return Stop()

    if "check" in doc:
        cdef = ConditionDef(doc["call"], doc["check"], doc["op"], None, None)
        consequence = doc["consequence"]
        if consequence:
            cdef.consequence = []
            for field in consequence:
                cdef.consequence.append(_load_field_from_json(field))

        alternative = doc["alternative"]
        if alternative:
            cdef.alternative = []
            for field in alternative:
                cdef.alternative.append(_load_field_from_json(field))
        return cdef

    return FieldDef(doc["name"], doc["call"])


def _load_parcelable_from_json(doc: t.Dict[str, t.Any]) -> ParcelableDef:
    pdef = ParcelableDef(doc["qname"], Type[doc["type"]], [])
    for field in doc["fields"]:
        pdef.fields.append(_load_field_from_json(field))
    return pdef
