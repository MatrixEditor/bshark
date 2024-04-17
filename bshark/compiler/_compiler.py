import os
import typing as t
import aidl

from bshark import FULL_AIDL_EXT

from bshark.compiler.model import (
    ParcelableDef,
    BinderDef,
    FieldDef,
    MethodDef,
    ParameterDef,
    ReturnDef,
    Stop,
    ConditionDef,
    ImportDef,
    ImportDefList,
    Direction,
    Unit,
    QName,
    RPath,
    Type,
    Complex,
    Primitive,
    UnsupportedTypeError,
)
from bshark.compiler.loader import BaseLoader
from bshark.compiler.util import to_qname, get_rpath


class Introspector:

    def __init__(self, unit: Unit, loader: BaseLoader) -> None:
        self.unit = unit
        self.loader = loader
        self.imports = None
        if unit.types[0].body is None:
            raise UnsupportedTypeError(
                f"Only parcelable or binder with a body are supported (at {self.qname!r})"
            )
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

    def resolve_parcel_call_from_tracker(
        self, method: aidl.tree.MethodInvocation
    ) -> t.Optional[aidl.tree.MethodInvocation]:
        """Resolve a parcel call from a method invocation on the tracker."""
        match method.member:
            case "readTypedList":
                target = method.arguments[1]
                if target.member != "CREATOR":
                    raise ValueError(
                        f"Expected CREATOR in readTypedList call - got {target.member!r}"
                    )
                target_name = target.qualifier
                return f"readTypedList:{self.imports.get(target_name).qname}"

            case "readTypedObject":
                ref = method.arguments[0]
                if ref.member != "CREATOR":
                    raise ValueError(
                        f"Expected CREATOR in readTypedObject call - got {ref!r}"
                    )
                target_name = ref.qualifier
                return f"readTypedObject:{self.imports.get(target_name).qname}"

            case _:
                # By defaulr we just record the method name
                return method.member

    def get_target_parcel_method(
        self, method: aidl.tree.MethodInvocation, tracker: str
    ) -> t.Optional[str]:
        method = self._method_from_expression(method)
        if method.qualifier == tracker:
            # we assert here that the method is an invocation of the tracker
            # TODO: implement rules
            return self.resolve_parcel_call_from_tracker(method)

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

    def get_member_type(self, name: str) -> t.Optional[aidl.tree.Type]:
        for field in self.type.fields:
            if field.declarators[0].name == name:
                return field.type

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
                        # We have two types of delegates:
                        #   1. Delegate parsing to antother parcelable
                        #   2. Delegate parsing to a local method
                        qualifier = stmt.expression.qualifier
                        if not qualifier:
                            # second case
                            try:
                                method = self.get_method(stmt.expression.member)
                            except ValueError:
                                continue  # method is not within this scope
                            body = method.body
                            method_tracker = self.get_parcel_tracker(method.parameters)
                            members.extend(
                                self._parse_parcelable_java(body, method_tracker)
                            )
                        else:
                            # try to resolve the type of the delegate
                            member_ty = self.get_member_type(qualifier)
                            if not member_ty:
                                raise ValueError(
                                    f"Could not resolve type of {qualifier!r}"
                                )
                            call = self.get_call(member_ty)
                            members.append(FieldDef(qualifier, call))

                    elif stmt.expression.qualifier == tracker:
                        # the statement is a call to the current Parcel
                        # object.
                        method = stmt.expression
                        call = self.resolve_parcel_call_from_tracker(method)
                        members.append(FieldDef(tracker, call))

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
                if not ty.arguments:
                    # No type arguments -> return fallback instead
                    return f"readParcelable{array}:java.util.List"

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
            if ext in (FULL_AIDL_EXT, ".java", ".json"):
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
            if not ctor and not creator:
                raise UnsupportedTypeError(
                    f"Class {self.qname} is not a parcelable class"
                )
            if self.is_constructor_delegate(creator) and ctor:
                # Just use the constructor directly
                target = ctor
            elif creator:
                target = creator

            pdef.fields = self.parcelable_java(target)
        return pdef
