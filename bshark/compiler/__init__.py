import enum
import os
import aidl
import dataclasses as dc
import typing as t
import json

from bshark import AIDL_EXT, FULL_AIDL_EXT

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

Unit = aidl.tree.CompilationUnit
"""A parsed source code unit.

Instances of this class include AIDL classes as well as Java classes.
"""

SPECIAL_TYPES = []


# Parcelable Operations: (special)
#
# createLongArray <=> readInt64Vector
#
class UnsupportedTypeError(TypeError):
    pass


def filterclasses(body):
    return filter(lambda t: isinstance(t, aidl.tree.ClassDeclaration), body)


def filtertypes(body):
    return filter(lambda t: isinstance(t, aidl.tree.TypeDeclaration), body)


def is_parcelable_unit(decl: aidl.tree.ClassDeclaration) -> bool:
    return any(ty.name == "Parcelable" for ty in decl.implements)


def filteraidl(files):
    return filter(lambda f: f.endswith(FULL_AIDL_EXT), files)


class Type(enum.Enum):
    """The type of a unit."""

    PARCELABLE = 0
    PARCELABLE_JAVA = 1
    BINDER = 2  # conforms to an interface
    SPECIAL = 3
    UNDEFINED = 4


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


def to_qname(unit: Unit) -> QName:
    """Get the qualified name of a unit."""
    ty = unit.types[0]
    if isinstance(ty, ClassDef):
        return ty.qname

    return ".".join([unit.package.name, ty.name])


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

    def parse_java(self, abs_path: str) -> t.List[Unit]:
        """Parses the given java file and stores all parcelable units."""
        with open(abs_path, "r", encoding="utf-8") as f:
            try:
                unit = aidl.fromstring(f.read(), is_aidl=False)
            except aidl.JavaSyntaxError as err:
                raise SyntaxError(f"{abs_path} is not a valid java file") from err

        result = []
        qname = to_qname(unit)
        # pylint: disable-next=no-member
        for defined_type in unit.types:
            # pylint: disable-next=no-member
            result.extend(self._load_inner_classes(defined_type, qname, unit.imports))
        return result

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
                package=base_qname, imports=imports, types=[base_unit]
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
            definition = fromobj(json.load(f))

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
        for defined_type in filterclasses(body):
            # the qualified name may contain '$' to indicate that we
            # have a reference to an inner class.
            raw_qname = f"{base_package}.{defined_type.name}"
            inner = raw_qname.count("$") > 0
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
                        self.parse_java(java_abs_path)
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
        return list(self.load_aidl(f"{rel_path}.aidl"))


class Primitive:
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
    }


class Complex:
    VALUES = {
        "IBinder": "readStrongBinder",
        "android.os.IBinder": "readStrongBinder",
        # "ParcelFileDescriptor": "readParcelable:android.os.ParcelFileDescriptor",
        "Bundle": "readBundle",
        "android.os.Bundle": "readBundle",
    }


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
    retval: t.Optional[t.List[ParameterDef | ReturnDef]]
    arguments: t.List[ParameterDef]

    def is_oneway(self) -> bool:
        return self.retval is None

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
    fields: t.List[FieldDef]


@dc.dataclass(slots=True)
class ClassDef:
    """A simple generic type definition."""

    qname: str
    type: Type


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
    pass


class ImportDefList(list):

    def get(self, name: str) -> t.Optional[ImportDef]:
        return next(filter(lambda x: x.name == name, self), None)


class Introspector:

    def __init__(self, unit: Unit, loader: BaseLoader) -> None:
        self.unit = unit
        self.loader = loader
        self.imports = None
        # now parse them
        self.imports = self.get_imports()

    @property
    def qname(self) -> QName:
        return to_qname(self.unit)

    @property
    def type(self) -> aidl.tree.TypeDeclaration:
        return self.unit.types[0]

    @property
    def rpath(self) -> RPath:
        return get_rpath(self.qname)

    @property
    def members(self) -> t.List[str]:
        return list(map(lambda x: x.declarators[0].name, self.type.fields))

    @property
    def creator(self) -> t.Optional[aidl.tree.MethodDeclaration]:
        """Resolves the CREATOR field in a parcelable class."""

        for field in self.type.fields:
            if len(field.declarators) != 1:
                continue

            declarator = field.declarators[0]
            if declarator.name == "CREATOR":
                # Now, search for createFromParcel method within the anonymous class
                for decl in declarator.initializer.body:
                    if not isinstance(decl, aidl.tree.MethodDeclaration):
                        continue

                    if decl.name == "createFromParcel":
                        return decl

                break

        # we don't want to throw an error here, just return None
        return None

    @property
    def constructor(self) -> t.Optional[aidl.tree.ConstructorDeclaration]:
        """Resolves the constructor in a parcelable class."""

        # constructor := <class>(Parcel in) { ... }
        for ctor in self.type.constructors:
            if len(ctor.parameters) != 1:
                continue

            param = ctor.parameters[0]
            param_ty = param.type
            if not getattr(param_ty, "sub_type", None):
                if param_ty.name == "Parcel":
                    return ctor
                continue

            if (
                param_ty.sub_type
                and param_ty.sub_type.sub_type
                and param_ty.sub_type.sub_type.name == "Parcel"
            ):
                return ctor

        # we don't want to throw an error here, just return None
        return None

    @property
    def fallback_method(self) -> aidl.tree.MethodDeclaration:
        """Resolves the fallback method in a parcelable class."""

        # If everything else does not work we have to use this
        # fallback method
        return self.get_method("writeToParcel")

    def get_method(self, name: str) -> aidl.tree.MethodDeclaration:
        """Resolves the fallback method in a parcelable class."""

        # If everything else does not work we have to use this
        # fallback method
        for method in self.type.methods:
            if method.name == name:
                return method
        raise ValueError("Could not find fallback method")

    def _method_from_expression(
        self, expr: aidl.tree.Expression
    ) -> t.Optional[aidl.tree.MethodInvocation]:
        value = expr
        match value:
            case aidl.tree.MethodInvocation():
                pass
            case aidl.tree.Cast():
                value = value.expression
            case aidl.tree.BinaryOperation(operandl=aidl.tree.MethodInvocation()):
                value = value.operandl
            case aidl.tree.BinaryOperation(operandr=aidl.tree.MethodInvocation()):
                value = value.operandr
            case _:
                return None
        return value

    def is_assignment(
        self, expression: aidl.tree.Expression, tracker: t.Optional[str]
    ) -> bool:
        """Check if an expression is an assignment."""
        if not isinstance(expression, aidl.tree.StatementExpression):
            return False

        if not isinstance(expression.expression, aidl.tree.Assignment):
            return False

        if not tracker:
            return True

        # check if the value is a method invocation
        value = self._method_from_expression(expression.expression.value)
        if not value:
            return False

        # the assignment may be a call to another CREATOR, therefore
        # the qualifier or first parameter can be the value of the
        # tracker.
        if value.qualifier == tracker:
            return True

        if len(value.arguments) < 1:
            return False

        arg = value.arguments[0]
        return isinstance(arg, aidl.tree.MemberReference) and arg.member == tracker

    def is_assigned_to_member(self, assignment: aidl.tree.Assignment) -> bool:
        """Check if an assignment points to a member."""
        left = assignment.expressionl
        match left:
            case aidl.tree.This():
                # In case where the code defines this.<member> directly,
                # we will be able to resolve it
                return True

            case aidl.tree.MemberReference():
                return left.member in self.members

        # the current statement is not an assignment to a member, but
        # may encapsulate a local variable to a member
        return False

    def get_assigned_member(self, assignment: aidl.tree.Assignment) -> str:
        """Get the name of the member that is being assigned to."""
        left = assignment.expressionl
        match left:
            case aidl.tree.This():
                # In case where the code defines this.<member> directly,
                # the selector will give us the member's name
                return left.selectors[0].member

            case aidl.tree.MemberReference():
                return left.member

        raise ValueError("Could not get assigned member")

    def is_constructor_delegate(self, method: aidl.tree.MethodDeclaration) -> bool:
        """Check if a method is a constructor delegate."""

        # CREATOR instances often delegate parsing to the constructor of a
        # class. In this case, the first element of the body is a method
        # call to the constructor.
        if len(method.body) != 1:
            return False

        body = method.body
        # The body simply contains:
        #  return <class>(parcel);
        if isinstance(body[0], aidl.tree.ReturnStatement):
            if isinstance(body[0].expression, aidl.tree.ClassCreator):
                return True

        return False

    def is_delegate(self, incovation: aidl.tree.MethodInvocation, tracker: str) -> bool:
        """Check if a method is a delegate to another internal method (not constructor)"""
        if len(incovation.arguments) != 1:
            return False

        target_arg = incovation.arguments[0]
        return (
            isinstance(target_arg, aidl.tree.MemberReference)
            and target_arg.member == tracker
        )

    def get_parcel_tracker(self, parameters: t.List[aidl.tree.FormalParameter]) -> str:
        """Get the name of the parcel tracker."""
        return parameters[0].name

    def is_local_variable(
        self, expression: aidl.tree.LocalVariableDeclaration, tracker: str
    ) -> bool:
        """Check if an expression is a local variable. and contains the parcel tracker."""
        if not isinstance(expression, aidl.tree.LocalVariableDeclaration):
            return False

        declarator = expression.declarators[0]
        if not isinstance(declarator, aidl.tree.VariableDeclarator):
            return False

        initializer = declarator.initializer
        return (
            isinstance(initializer, aidl.tree.MethodInvocation)
            and initializer.qualifier == tracker
        )

    def get_target_parcel_method(
        self, method: aidl.tree.MethodInvocation, tracker: str
    ) -> t.Optional[str]:
        method = self._method_from_expression(method)
        if method.qualifier == tracker:
            # we assert here that the method is an invocation of the tracker
            return method.member

        # qualifier shows us the target class
        if "CREATOR" in method.qualifier and method.member == "createFromParcel":
            name, _ = method.qualifier.rsplit(".", 1)
            # the first part is the target class
            target_class = self.imports.get(name)
            if target_class:
                return f"readParcelable:{target_class.qname}"

        if method.member == "readFromParcel" and method.arguments[0].member == tracker:
            target_class = method.qualifier
            return f"readParcelable:{self.imports.get(target_class).qname}"

        # iterate over each argument and check if the qualifier
        # is the tracker
        for arg in method.arguments:
            if isinstance(arg, aidl.tree.MethodInvocation):
                if arg.qualifier == tracker:
                    return arg.member

        return None

    def trace_member(
        self,
        body: t.List[aidl.tree.StatementExpression],
        offset: int,
        assignment: aidl.tree.LocalVariableDeclaration,
    ) -> t.Tuple[str]:
        """Tries to trace the name of the member being assigned to.

        This function will inspect all member assignments along the way starting
        from the given offset in the method body.
        """

        # Make sure that the assignment is a variable declaration
        declarator: aidl.tree.VariableDeclarator = assignment.declarators[0]
        if not isinstance(declarator, aidl.tree.VariableDeclarator):
            raise TypeError(f"Expected VariableDeclarator, got {type(declarator)}")

        var_name: str = declarator.name
        if var_name in self.members:
            return var_name

        for i in range(offset + 1, len(body)):
            stmt = body[i]
            # We first check for an assignment statement and then
            # check if the expression contains the variable name
            # we are looking for.
            if self.is_assignment(stmt, tracker=None) and self.is_assigned_to_member(
                stmt.expression
            ):
                member = self.get_assigned_member(stmt.expression)
                initializer = stmt.expression.value
                match initializer:
                    # In case where the temporary variable contains an extra method call,
                    # we have to ckeck for the qualifier of a method invocation.
                    case aidl.tree.MethodInvocation():
                        if initializer.qualifier == var_name:
                            return member

        # fallback to variable name
        return var_name

    def is_nullable_check(
        self, if_statement: aidl.tree.IfStatement, tracker: str
    ) -> bool:
        """Checks if the given IF statement is a nullable check."""
        if not isinstance(if_statement.condition, aidl.tree.BinaryOperation):
            return False

        left = if_statement.condition.operandl
        right = if_statement.condition.operandr
        for x in [left, right]:
            if isinstance(x, aidl.tree.MethodInvocation):
                if x.qualifier == tracker:
                    return True
        return False

    def get_constant_value(self, statement: aidl.tree.Primary) -> t.Any:
        match statement:
            case aidl.tree.Literal():
                return statement.value
            case aidl.tree.MemberReference():
                return statement.member

        raise ValueError(f"Could not get constant value from {statement}")

    def get_nullable_check(
        self, if_statement: aidl.tree.IfStatement, tracker: str
    ) -> ConditionDef:
        left = if_statement.condition.operandl
        right = if_statement.condition.operandr
        for x in [left, right]:
            if isinstance(x, aidl.tree.MethodInvocation):
                if x.qualifier == tracker:
                    val = left if x is right else right
                    return ConditionDef(x.member, self.get_constant_value(val), [])
        raise ValueError("Could not find nullable check")

    def _parse_parcelable_java(
        self, body: t.List[aidl.tree.Statement], tracker: str
    ) -> t.List[FieldDef | ConditionDef]:
        members = []
        # We iterate over all statements in the body and look out
        # for delegations, assignments and local variables.
        for j, stmt in enumerate(body):
            match stmt:
                # If this statement is a delegate, we have to first parse
                # the invoked method.
                case aidl.tree.StatementExpression(
                    expression=aidl.tree.MethodInvocation()
                ):
                    if self.is_delegate(stmt.expression, tracker):
                        try:
                            method = self.get_method(stmt.expression.member)
                        except ValueError:
                            continue  # method is not within this scope
                        members.extend(self.parcelable_java(method))

                    elif stmt.expression.qualifier == tracker:
                        # the statement is a call to the current Parcel
                        # object.
                        method = stmt.expression
                        match method.member:
                            case "readTypedList":
                                member = method.arguments[0].member
                                target = method.arguments[1]
                                if not target.member == "CREATOR":
                                    raise ValueError(
                                        f"Expected CREATOR in readTypedList call - got {target.member!r}"
                                    )
                                target_name = target.qualifier[0]
                                func = f"readTypedList:{self.imports.get(target_name).qname}"
                                members.append(FieldDef(member, func))

                # If this statement is an assignment, we have to check
                # if it is a member assignment or a local variable
                case aidl.tree.StatementExpression(expression=aidl.tree.Assignment()):
                    # The assignment must explicitly contain the tracker
                    if not self.is_assignment(stmt, tracker):
                        continue

                    if self.is_assigned_to_member(stmt.expression):
                        member = self.get_assigned_member(stmt.expression)
                        func = self.get_target_parcel_method(
                            stmt.expression.value, tracker
                        )
                        members.append(FieldDef(member, func))

                # In case where the statement is a local variable declaration,
                # we try to trace the name of the member being assigned to.
                case aidl.tree.LocalVariableDeclaration():
                    if not self.is_local_variable(stmt, tracker):
                        continue
                    func = self.get_target_parcel_method(
                        stmt.declarators[0].initializer, tracker
                    )
                    member = self.trace_member(body, j, stmt)
                    members.append(FieldDef(member, func))

                # we will trace if statements as they may contain additional members
                case aidl.tree.IfStatement():
                    if self.is_nullable_check(stmt, tracker):
                        cond = self.get_nullable_check(stmt, tracker)
                        cond.fields += self._parse_parcelable_java(
                            stmt.then_statement.statements, tracker
                        )
                        members.append(cond)

                # Return statement with (possible) tracker as argument
                case aidl.tree.ReturnStatement(expression=aidl.tree.ClassCreator()):
                    ctor = stmt.expression
                    if len(ctor.arguments) == 1 and ctor.arguments[0].member == tracker:
                        ctor = self.constructor
                        members += self._parse_parcelable_java(ctor.body, tracker)

                case aidl.tree.ReturnStatement():
                    # end the loop on other return statements
                    members.append(Stop())
                    break

        return members

    def parcelable_java(
        self, method: aidl.tree.MethodDeclaration
    ) -> t.List[FieldDef | ConditionDef]:
        """
        Processes the given method declaration and returns a dictionary
        of internal members and their corresponding parcel methods.
        """
        if self.loader.ccache[self.qname] != Type.PARCELABLE_JAVA:
            raise ValueError("Not a parcelable java class")

        tracker = self.get_parcel_tracker(method.parameters)
        body = method.body
        return self._parse_parcelable_java(body, tracker)

    def parcelable(self) -> t.List[FieldDef | ConditionDef]:
        """Process this class and return all fields."""
        members = []
        if self.type.cpp_header:
            raise UnsupportedTypeError("CPP header files are not supported")

        for field in self.type.fields:
            if "static" in field.modifiers:
                continue
            # We are processing ConstantDeclaration objects, which usually
            # store the VariableDeclarator and its type.
            declarator = field.declarators[0]
            members.append(FieldDef(declarator.name, self.get_call(field.type)))
        return members

    def get_full_type(self, ref_ty: aidl.tree.ReferenceType) -> aidl.tree.ReferenceType:
        parts = [ref_ty.name]
        current = ref_ty.sub_type
        while current:
            parts.append(current.name)
            current = current.sub_type
        return aidl.tree.Type(name=".".join(parts))

    def get_call(self, ty: aidl.tree.Type) -> t.Optional[str]:
        # If the parameter is an imported type we have to
        # check its inferred type (binder, parcelable, etc)
        array = "Vector" if len(ty.dimensions or []) != 0 else ""
        if ty.name in Primitive.VALUES:
            return f"read{ty.name.capitalize()}{array}"

        if ty.name in Complex.VALUES:
            return Complex.VALUES[ty.name] + array

        # fallback classes
        match ty.name:
            case "List" | "java.util.List":
                ref_ty = self.get_full_type(ty.arguments[0].type)
                if ref_ty.name in self.imports:
                    return f"readList:{self.imports.get(ref_ty.name).qname}"
                if ref_ty.name in Complex.VALUES:
                    return f"readList:{Complex.VALUES[ref_ty.name]}"

                return f"readList:{ref_ty.name}"

        if ty.name in self.imports:
            item = self.imports.get(ty.name)
            if item and item.file_type == Type.BINDER:
                return f"readStrongBinder{array}"
            # We assert all other types are parcelable classes,
            # even if we can't import them.
            return f"readParcelable{array}:{item.qname}"

        if isinstance(ty, aidl.tree.ReferenceType) and ty.sub_type:
            parts = [ty.name]
            current = ty.sub_type
            while current:
                parts.append(current.name)
                current = current.sub_type
            return self.get_call(aidl.tree.Type(name=".".join(parts)))

        # last fallback option: current directory
        cname = ty.name
        rel_dir_path = ty.name.replace(".", "/")
        match ty.name.count("."):
            case 1:  # inner class in the current package
                cname, _ = ty.name.split(".")
                qname = f"{self.unit.package.name}.{ty.name}"
                rel_dir_path = os.path.sep.join(qname.split(".")[:-2])
            case 0:  # class in the current package
                cname = ty.name
                qname = f"{self.unit.package.name}.{ty.name}"
                rel_dir_path = os.path.sep.join(qname.split(".")[:-1])
            case _:
                parts = ty.name.split(".")
                qname = ty.name
                if parts[-2][0].isupper():
                    # inner class in another package
                    cname = parts[-2]
                    rel_dir_path = "/".join(parts[:-2])
                else:
                    cname = parts[-1]
                    rel_dir_path = "/".join(parts[:-1])

        try:
            abs_dir_path = self.loader.to_absolute(rel_dir_path)
        except FileNotFoundError:
            # TODO: fix
            return f"readParcelable{array}:{qname}"

        for fname in os.listdir(abs_dir_path):
            # check without extension
            name, extension = os.path.splitext(fname)
            if name == cname:
                unit_type = None
                if qname in self.loader.ccache:
                    unit_type = self.loader.ccache[qname]

                elif extension == "aidl":
                    self.loader.import_(qname)
                    unit_type = self.loader.ccache[qname]

                return (
                    f"readParcelable{array}:{qname}"
                    if unit_type != Type.BINDER
                    else f"readStrongBinder{array}"
                )

    def _perform_import(self, qname: str) -> t.List[ImportDef]:
        try:
            imported_units = self.loader.import_(qname)
        except (ImportError, FileNotFoundError):
            return [ImportDef(qname)]

        result = []
        for imported_unit in (
            imported_units if isinstance(imported_units, list) else [imported_units]
        ):
            qname = to_qname(imported_unit)
            def_type = Type.PARCELABLE
            if qname in self.loader.ccache:
                def_type = self.loader.ccache[qname]

            result.append(
                ImportDef(
                    qname,
                    def_type,
                    imported_unit,
                )
            )
        return result

    def get_imports(self) -> ImportDefList:
        """Resolves the imports in the underlying class."""
        if self.imports is not None:
            return self.imports

        imports = ImportDefList()
        for import_decl in self.unit.imports:
            if import_decl.static:
                continue
            imports.extend(self._perform_import(import_decl.path))

        # fallback: import all files from the current directory
        parts = self.unit.package.name.split(".")
        if parts[-1][0].isupper():
            parts = parts[:-1]

        rel_dir_path = os.path.sep.join(parts)
        abs_dir_path = self.loader.to_absolute(rel_dir_path)
        for fname in os.listdir(abs_dir_path):
            name, ext = os.path.splitext(fname)
            if ext == FULL_AIDL_EXT:
                qname = ".".join(parts + [name])
                imports.extend(self._perform_import(qname))

        return imports

    def as_binder(self) -> BinderDef:
        """
        Processes the given method declarations and returns a dictionary
        of internal members and their corresponding parcelable calls
        """
        if self.loader.ccache[self.qname] != Type.BINDER:
            raise ValueError("Not a binder class")

        bdef = BinderDef(self.qname, Type.BINDER.name, None)
        # at first, we have to import all the referenced classes
        members = set()
        for method in self.type.methods:
            item = MethodDef(
                method.name,
                method.code,
                arguments=[],
                retval=(None if not method.return_type else []),
            )
            is_oneway = item.retval is None

            if not is_oneway:
                item.retval.append(ReturnDef(self.get_call(method.return_type)))

            for parameter in method.parameters:
                param_ty = parameter.type
                param_def = ParameterDef(parameter.name, self.get_call(param_ty))
                if "out" in parameter.modifiers:
                    # TODO: explain
                    if is_oneway:
                        item.retval = []
                    #     raise ValueError(
                    #         f"Oneway method ({item.name}) cannot have 'out' parameters in class {bdef.qname}"
                    #     )
                    item.retval.append(param_def)
                    param_def.direction = Direction.OUT
                else:
                    item.arguments.append(param_def)

            members.add(item)

        bdef.methods = list(sorted(members, key=lambda x: x.tc))
        return bdef

    def as_parcelable(self) -> ParcelableDef:
        """
        Processes the given unit as a parcelable class and returns a dictionary
        of internal members and their corresponding parcelable calls
        """
        ty = self.loader.ccache[self.qname]
        if ty not in (
            Type.PARCELABLE,
            Type.PARCELABLE_JAVA,
        ):
            raise ValueError(f"Not a parcelable class - got {ty}")

        pdef = ParcelableDef(self.qname, ty.name, None)
        if ty == Type.PARCELABLE:
            pdef.fields = self.parcelable()
        else:
            # We are using the CREATOR instance as our entry point
            # and will follow all method calls from there.
            ctor = self.constructor
            creator = self.creator
            if self.is_constructor_delegate(creator) and ctor:
                # Just use the constructor directly
                target = ctor
            elif creator:
                target = creator

            pdef.fields = self.parcelable_java(target)
        return pdef


def tojson(definition):
    obj = definition
    if isinstance(definition, t.Iterable):
        obj = [dc.asdict(o) for o in definition]
    else:
        obj = dc.asdict(definition)
    return json.dumps(obj, indent=2)


def fromjson(data, ty: Type) -> t.Optional[BinderDef | ParcelableDef]:
    obj = json.loads(data)
    match ty:
        case Type.BINDER:
            return BinderDef(**obj)
        case Type.PARCELABLE:
            return ParcelableDef(**obj)

    return None


def fromobj(doc: t.Dict[str, t.Any]) -> t.Optional[BinderDef | ParcelableDef]:
    if "type" not in doc:
        return None

    ty = Type[doc["type"]]
    if ty == Type.BINDER:
        return _load_binder_from_json(doc)

    if ty in (Type.PARCELABLE, Type.PARCELABLE_JAVA):
        return _load_parcelable_from_json(doc)

    return None


def _load_binder_from_json(doc: t.Dict[str, t.Any]) -> BinderDef:
    bdef = BinderDef(doc["qname"], Type.BINDER, [])
    for method in doc["methods"]:
        mdef = MethodDef(method["name"], method["tc"], None, [])
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
        cdef = ConditionDef(doc["call"], doc["check"], [])
        for field in doc["fields"]:
            cdef.fields.append(_load_field_from_json(field))
        return cdef

    return FieldDef(doc["name"], doc["call"])


def _load_parcelable_from_json(doc: t.Dict[str, t.Any]) -> ParcelableDef:
    pdef = ParcelableDef(doc["qname"], Type[doc["type"]], [])
    for field in doc["fields"]:
        pdef.fields.append(_load_field_from_json(field))
    return pdef
