import os
import json
import aidl
import typing as t

from bshark.compiler.model import Unit, QName, RPath, Type
from bshark.compiler.model import ABSPath, from_json
from bshark.compiler.util import is_parcelable_unit, get_qname, to_qname
from bshark.compiler.util import filteraidl, filterclasses, filtertypes
from bshark.compiler.util import get_declaring_class, get_class_name


class BaseLoader:

    def __init__(
        self,
        path: t.List[str],
        uc: t.Optional[dict] = None,
        cc: t.Optional[dict] = None,
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
        self.ccache: dict[QName, Type] = cc or {}

    def parse_java(self, abs_path: str, qname: t.Optional[str] = None) -> t.List[Unit]:
        """Parses the given java file and stores all parcelable units."""
        with open(abs_path, "r", encoding="utf-8") as f:
            try:
                unit = aidl.fromstring(f.read(), is_aidl=False)
            except aidl.JavaSyntaxError as err:
                raise SyntaxError(f"{abs_path} is not a valid java file") from err

        result = []
        # pylint: disable-next=no-member
        for defined_type in unit.types:
            # NOTE: we have to use the package here instead of the qname
            result.extend(
                # pylint: disable-next=no-member
                self._load_inner_classes(defined_type, unit.package.name, unit.imports)
            )

        # Sometimes, the class does not directly implement the Parcelable
        # interface, so we have to add the type manually
        if qname and qname not in self.ucache:
            unit_qname = to_qname(unit)
            if unit_qname == qname:
                self.ucache[qname] = unit
                self.ccache[qname] = Type.PARCELABLE_JAVA
            else:
                self._add_exact_class(
                    unit.types[0], to_qname(unit), qname, unit.imports
                )
                if qname not in self.ucache:
                    # This should never happen, but we will add a phantom unit,
                    # which stores only the class name
                    package = get_declaring_class(qname)
                    self.ucache[qname] = Unit(
                        package=aidl.tree.PackageDeclaration(name=package),
                        imports=unit.imports,
                        types=[aidl.tree.TypeDeclaration(name=get_class_name(qname))],
                    )
                    self.ccache[qname] = Type.PARCELABLE_JAVA

            result.append(self.ucache[qname])
        return result

    def _add_exact_class(
        self, unit: aidl.tree.TypeDeclaration, package: str, qname: str, imports
    ) -> None:
        for ty in filterclasses(unit.body):
            ty_qname = f"{package}.{ty.name}"
            if ty_qname == qname:
                self.ccache[qname] = Type.PARCELABLE_JAVA
                self.ucache[qname] = Unit(
                    package=aidl.tree.PackageDeclaration(name=package),
                    imports=imports,
                    types=[ty],
                )
                break
            self._add_exact_class(ty, package, qname, imports)

    def _load_inner_classes(
        self, base_unit: aidl.tree.TypeDeclaration, base_qname: str, imports
    ) -> t.List[Unit]:
        """
        Loads the inner classes of the given base unit (only for parcelable units).
        """
        units = []
        qname = f"{base_qname}.{base_unit.name}"
        if is_parcelable_unit(base_unit):
            u = aidl.tree.CompilationUnit(
                package=aidl.tree.PackageDeclaration(name=base_qname),
                imports=imports,
                types=[base_unit],
            )
            self.ccache[qname] = Type.PARCELABLE_JAVA
            self.ucache[qname] = u
            units.append(u)

        for ty in filterclasses(base_unit):
            units += self._load_inner_classes(ty, qname, imports)
        return units

    def parse_aidl(self, abs_path: ABSPath) -> Unit:
        """Parses the given aidl file and returns the parsed unit without caching it."""
        with open(abs_path, "r", encoding="utf-8") as f:
            try:
                unit = aidl.fromstring(f.read(), is_aidl=True)
            except aidl.JavaSyntaxError as err:
                raise SyntaxError(f"{abs_path} is not a valid AIDL file") from err
        return unit

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
        unit = aidl.tree.CompilationUnit(
            package=aidl.tree.PackageDeclaration(name=package),
            types=[definition],
            imports=[],
        )
        self.ccache[qname] = definition.type
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
        self, body, base_package: str, imports, aidl_rpath: RPath
    ) -> t.List[Unit]:
        """Processes an aidl unit and returns the cached units."""
        types = []
        for defined_type in filtertypes(body):
            # the qualified name may contain '$' to indicate that we
            # have a reference to an inner class.
            raw_qname = f"{base_package}.{defined_type.name}"
            qname = raw_qname.replace("$", ".")

            # Use cached units whenever possible
            if qname in self.ucache:
                types.append(self.ucache[qname])
                continue

            # We have to types of declarations
            match defined_type:
                # 1. An interface defines a service, which will be
                # translated into a binder.
                case aidl.tree.InterfaceDeclaration():
                    self.ccache[qname] = Type.BINDER

                # 2. An direct parcelable class to import
                case aidl.tree.ParcelableDeclaration():
                    self.ccache[qname] = Type.PARCELABLE
                    if not defined_type.body:
                        # Parcelable definitions may not store a body and
                        # therefore can be a reference to an existing Java
                        # class.
                        self.ccache[qname] = Type.PARCELABLE_JAVA
                        # Now, we try to resolve the Java equivalent
                        java_rel_path = aidl_rpath.replace(".aidl", ".java")
                        java_abs_path = self.to_absolute(java_rel_path)
                        # Actually, we do not need to inspect the result here,
                        # because the method already stores the required unit.
                        self.parse_java(java_abs_path, qname)
                        types.append(self.ucache[qname])
                        continue

            # create the new type
            if qname in self.ccache:
                unit = aidl.tree.CompilationUnit(
                    package=aidl.tree.PackageDeclaration(name=base_package),
                    imports=imports,
                    types=[defined_type],
                )
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
        # We have to collect all classes, event if they are marked
        # as inner classes in the aidl file.
        result = self._process_aidl_unit(
            # pylint: disable-next=no-member
            unit.types,
            unit.package.name,
            unit.imports,
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
        for fname in filteraidl(os.listdir(abs_dir_path)):
            result.extend(self.load_aidl(os.path.join(rpath, fname)))
        return result

    def _import_one(self, rpath: RPath) -> t.List[Unit]:
        """
        Imports the given .aidl or .java file and returns all defined
        units
        """
        if rpath.endswith(".aidl"):
            return list(self.load_aidl(rpath))

        if rpath.endswith(".java"):
            return list(self.parse_java(self.to_absolute(rpath)))

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
            abs_path = self.to_absolute(full_rpath)
            if os.path.exists(abs_path):
                return self._import_one(full_rpath)
