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
import os
import json
import typing as t

from tree_sitter import Node

from bshark import FULL_AIDL_EXT
from bshark.aidl import (
    JAVA,
    AIDL,
    parse_java,
    parse_aidl,
    get_package,
    get_imports,
    get_class_by_name,
    Unit,
    Type,
)
from bshark.compiler.util import get_qname, filteraidl
from bshark.compiler.model import QName, RPath, ABSPath, from_json


class BaseLoader:

    def __init__(
        self,
        path: t.List[str],
        uc: t.Optional[dict] = None,
    ):
        """
        Initializes the loader.

        :param path: the search path
        :type path: t.List[str]
        :param uc: a pre-loaded unit cache, defaults to None
        :type uc: t.Optional[dict], optional
        :param cc: a pre-loaded class cache, defaults to None
        :type cc: t.Optional[dict], optional
        """
        if not isinstance(path, list):
            raise ValueError("path must be a list of strings")

        if len(path) == 0:
            raise ValueError("path must not be empty")

        self.search_path = path
        self.ucache: dict[QName, Unit] = uc or {}

    def parse_java(
        self, abs_path: str, name: str, parent: t.Optional[str] = None
    ) -> Unit:
        """Parses the given java file and searches for the given class"""
        with open(abs_path, "rb") as f:
            unit = parse_java(f.read())

        if "." in name:
            parts = name.split(".")
            name = parts[-1]
            parent = ".".join(parts[:-1])

        class_decl = get_class_by_name(unit.root_node, name, JAVA)
        if not class_decl:
            # TODO: maybe add internal variable
            # raise ValueError(f"Could not find class {name!r} in {abs_path}")
            pass

        # Package must be queried from the root node
        package = get_package(unit.root_node, JAVA)
        if parent == package:
            parent = None

        imports = get_imports(unit.root_node, JAVA)
        qname = f"{package}.{name}" if not parent else f"{package}.{parent}.{name}"
        self.ucache[qname] = Unit(
            qname.rsplit(".", 1)[0],
            imports,
            name,
            Type.PARCELABLE_JAVA,
            class_decl,
        )
        return self.ucache[qname]

    def parse_aidl(self, abs_path: ABSPath) -> Unit:
        """Parses the given aidl file and returns the parsed unit without caching it."""
        with open(abs_path, "rb") as fp:
            return parse_aidl(fp.read())

    def parse_json(self, abs_path: ABSPath) -> Unit:
        """Parses the given json file and returns the cached unit"""
        with open(abs_path, "r", encoding="utf-8") as f:
            definition = from_json(json.load(f))

        # cache the unit, but first create appropriate rpath
        # and qname.
        qname = definition.qname
        parts = qname.split(".")
        classes = len(list(filter(lambda x: x[0].isupper(), parts)))
        package = ".".join(parts[:-classes])
        unit = Unit(package, [], parts[-1], definition.type, definition)
        self.ucache[qname] = unit
        return unit

    def to_absolute(self, rpath: RPath) -> ABSPath:
        """Converts a relative path to an absolute path."""
        for root in self.search_path:
            abs_path = os.path.join(root, rpath)
            if os.path.exists(abs_path):
                return abs_path

        raise FileNotFoundError(
            f"{rpath!r} not found in search path {self.search_path}"
        )

    def _process_aidl_unit(
        self, body: Node, base_package: str, imports, aidl_rpath: RPath
    ) -> t.List[Unit]:
        """Processes an aidl unit and returns the cached units."""
        types = []
        query = AIDL.query(
            """
            (parcelable_declaration) @type
            (interface_declaration) @type
            """
        )
        for defined_type, _ in query.captures(body):
            # the qualified name may contain '$' to indicate that we
            # have a reference to an inner class.
            name = defined_type.child_by_field_name("name").text.decode()
            qname = f"{base_package}.{name}"

            # Use cached units whenever possible
            if qname in self.ucache:
                types.append(self.ucache[qname])
                continue

            unit_ty = None
            # We have to types of declarations
            match defined_type.type:
                # 1. An interface defines a service, which will be
                # translated into a binder.
                case "interface_declaration":
                    unit_ty = Type.BINDER

                # 2. An direct parcelable class to import
                case "parcelable_declaration":
                    unit_ty = Type.PARCELABLE
                    if not defined_type.child_by_field_name("body"):
                        # Parcelable definitions may not store a body and
                        # therefore can be a reference to an existing Java
                        # class.
                        java_rel_path = aidl_rpath.replace(".aidl", ".java")
                        java_abs_path = self.to_absolute(java_rel_path)
                        # Actually, we do not need to inspect the result here,
                        # because the method already stores the required unit.
                        types.append(self.parse_java(java_abs_path, name, base_package))
                        continue

            # create the new type
            if unit_ty:
                unit = Unit(base_package, imports, name, unit_ty, defined_type)
                self.ucache[qname] = unit
                types.append(unit)

        return types

    def load_aidl(self, rpath: RPath) -> t.Tuple[Unit]:
        """
        Loads the given aidl file and returns all defined parcelable or
        binder units. This action will cache all loaded units and
        aditionally, it will try to resolve the Java equivalent of
        parcelables.

        This method will have no effect if the unit is already cached.
        """
        qname = get_qname(rpath)
        if qname in self.ucache:
            # just return the parsed unit
            return (self.ucache[qname],)

        abs_path = self.to_absolute(rpath)
        unit = self.parse_aidl(abs_path)

        imports = get_imports(unit.root_node, AIDL)
        package = get_package(unit.root_node, AIDL)
        # We have to collect all classes, event if they are marked
        # as inner classes in the aidl file.
        result = self._process_aidl_unit(
            unit.root_node,
            package,
            imports,
            rpath,
        )
        return tuple(result)

    def _import_wildcard(self, rpath: RPath) -> t.List[Unit]:
        """
        Imports all .aidl files in the given directory and returns
        all defined parcelable or binder units.
        """
        abs_dir_path = self.to_absolute(rpath)
        if not os.path.isdir(abs_dir_path):
            raise FileNotFoundError(f"{abs_dir_path!r} is not a directory")

        result = []
        for fname in os.listdir(abs_dir_path):
            _, ext = os.path.splitext(fname)
            match ext:
                case ".aidl":
                    result.extend(self.load_aidl(os.path.join(abs_dir_path, fname)))
                case ".json":
                    result.append(self.parse_json(os.path.join(abs_dir_path, fname)))
        return result

    def _import_one(self, rpath: RPath) -> t.List[Unit]:
        """
        Imports the given .aidl or .java file and returns all defined
        units
        """
        if rpath.endswith(".aidl"):
            return list(self.load_aidl(rpath))

        if rpath.endswith(".java"):
            qname = get_qname(rpath)
            package, name = qname.rsplit(".", 1)
            return [self.parse_java(self.to_absolute(rpath), name, package)]

        if rpath.endswith(".json"):
            return [self.parse_json(self.to_absolute(rpath))]

        raise FileNotFoundError(f"{rpath!r} is not an aidl or java file")

    def import_(self, qname: QName) -> t.List[Unit]:
        """
        Imports the given .aidl file and returns all defined units
        """
        parts = qname.split(".")
        if parts[-1] == "*":
            # wildcard import, import all .aidl files
            return self._import_wildcard("/".join(parts[:-1]))

        classes = len(list(filter(lambda x: x[0].isupper(), parts)))
        if classes == 1:
            rel_path = "/".join(parts)
        else:
            rel_path = "/".join(parts[: -(classes - 1)])

        for ext in (".aidl", ".java", ".json"):
            full_rpath = f"{rel_path}{ext}"
            try:
                self.to_absolute(full_rpath)
                return self._import_one(full_rpath)
            except FileNotFoundError:
                pass

        raise ImportError(
            (
                "The referenced class could not be resolved using .aidl, .java and "
                f".json imports. (referenced class: {qname!r})"
            )
        )
