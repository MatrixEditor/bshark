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
import typing as t

from tree_sitter import Node, Language

from bshark import FULL_AIDL_EXT
from bshark.aidl import (
    AIDL,
    JAVA,
    Unit,
    get_methods,
    get_binder_methods,
    get_parameters,
    get_parameter_modifier,
    get_class_by_name,
    Constants,
)
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
    QName,
    RPath,
    Type,
    Complex,
    Primitive,
    UnsupportedTypeError,
)
from bshark.compiler.loader import BaseLoader
from bshark.compiler.util import get_declaring_class


PARCEL_TYPE_NAME = "Parcel"
PARCEL_QNAME = f"android.os.{PARCEL_TYPE_NAME}"


# --- internal method ---
def txt(node: Node) -> t.Optional[str]:
    return node.text.decode() if node else None


# ---


class Preprocessor:
    """A preprocessor for AIDL files.

    This simple class can be used to view and inspect basic characteristics
    of AIDL (and Java) files. The base :class:`Unit` must be loaded first,
    e.g. by a :class:`BaseLoader`.
    """

    def __init__(self, unit: Unit) -> None:
        self.unit = unit
        # some processing must be done before we can compile
        # the given unit.
        self.members: t.Dict[str, Node] = self._get_members()
        self.methods: t.Dict[str, Node] = self._get_methods()
        self.constructors: t.List[Node] = self._get_constructors()
        self.extends: t.List[str] = self._get_superclasses()
        self.implements: t.List[str] = self._get_interfaces()

    @property
    def lang(self) -> Language:
        """Returns the language of the unit."""
        if self.unit.type in (Type.PARCELABLE, Type.BINDER):
            return AIDL
        return JAVA

    @property
    def qname(self) -> QName:
        """Returns the qualified name of the unit."""
        return f"{self.unit.package}.{self.unit.name}"

    @property
    def rpath(self) -> RPath:
        """Returns the relative path of the unit."""
        path = get_declaring_class(self.qname).replace(".", "/")
        if self.unit.type == Type.PARCELABLE_JAVA:
            return f"{path}.java"
        if self.is_compiled():
            return f"{path}.json"
        return path + FULL_AIDL_EXT

    @property
    def declared_class(self) -> t.Optional[Node]:
        """Returns the body of the unit."""
        return self.unit.body

    # --- public API methods ---

    def is_compiled(self) -> bool:
        """Returns whether the unit is already compiled."""
        return isinstance(self.unit.body, (ParcelableDef, BinderDef))

    def is_valid(self) -> bool:
        """Returns whether the unit is valid."""
        return self.unit.body is not None

    def get_creator(self) -> t.Optional[Node]:
        """Resolves the CREATOR field in a parcelable class."""
        field_decl = self.members.get("CREATOR")
        if not field_decl:
            return None

        # TODO: find a better way of getting the class body
        class_body = (
            field_decl.child_by_field_name("declarator")
            .child_by_field_name("value")
            .named_child(2)
        )
        methods = get_methods(class_body, self.lang, scope=class_body)
        return methods.get("createFromParcel")

    def get_parcel_constructor(self) -> t.Optional[Node]:
        """Resolves the constructor in a parcelable class."""
        for constructor in self.constructors:
            parameters = list(get_parameters(constructor, self.lang).values())

            # The constructor MUST have exactly one parameter and this
            # parameter must be of type Parcel.
            if len(parameters) != 1:
                continue

            type_name = parameters[0].child_by_field_name("type")
            if type_name.text.decode() in (PARCEL_TYPE_NAME, PARCEL_QNAME):
                return constructor

        # return nothing instead of throwing an exception as this
        # is an optional inspection element.
        return None

    # --- internal helpers ---

    def _get_members(self) -> t.Dict[str, Node]:
        """Processes all members of the current unit.

        This method will return a dictionary with the field's name
        mapped to the field's type.
        """
        if self.is_compiled() or not self.is_valid():
            return {}

        body = self.declared_class.child_by_field_name("body")
        query = self.lang.query(f"({Constants.FIELD_DECL}) @type")
        return {
            x.child_by_field_name("declarator")
            .child_by_field_name("name")
            .text.decode(): x
            for x, _ in query.captures(self.unit.body)
            if x.parent == body
        }

    def _get_methods(self) -> t.Dict[str, Node]:
        """Processes all methods of the current unit.

        This method will return a dictionary with the method's name
        mapped to the method's body.
        """
        if self.is_compiled() or not self.is_valid():
            return {}

        if self.unit.type == Type.BINDER:
            return get_binder_methods(self.unit.body)

        body = self.declared_class.child_by_field_name("body")
        return get_methods(self.unit.body, JAVA, scope=body)

    def _get_constructors(self) -> t.List[Node]:
        """Returns the constructors of the current unit."""
        if self.is_compiled() or not self.is_valid():
            return []

        query = self.lang.query(f"({Constants.CONSTUCTOR_DECL}) @type")
        body = self.declared_class.child_by_field_name("body")
        return [x for x, _ in query.captures(self.unit.body) if x.parent == body]

    def _get_superclasses(self) -> t.List[str]:
        """Returns the superclasses of the current unit."""
        if self.is_compiled() or not self.is_valid():
            return {}

        query = self.lang.query("(superclass) @type")
        results = query.captures(self.unit.body)
        return [
            txt(result.named_child(0))
            for result, _ in results
            if result.parent == self.unit.body
        ]

    def _get_interfaces(self) -> t.List[str]:
        """Returns the interfaces of the current unit."""
        if self.is_compiled() or not self.is_valid():
            return {}

        query = self.lang.query("(super_interfaces) @type")
        results = query.captures(self.unit.body)
        interfaces = []
        for super_interfaces, _ in results:
            if super_interfaces.parent == self.unit.body:
                interfaces.extend(
                    [txt(x) for x in super_interfaces.named_child(0).named_children]
                )
        return interfaces


class TypeHandler:
    """
    A special base class to support a mapping of type names to their
    corresponding Parcel calls.
    """

    def call_of(self, type_decl: Node, compiler: "Compiler") -> str:
        """Resolves the corresponding call in the Parcel class of a type name."""

        # 1. Check if there are dimensions associated with the type name
        array = "Vector" if type_decl.type == "array_type" else ""
        clean_name = type_decl.text.decode().replace("[]", "")

        # primitive values can be parsed directly
        if clean_name in Primitive.VALUES:
            return f"read{clean_name.capitalize()}{array}"

        # 2. Check if the type name is in the list of types
        # that are special
        if clean_name in Complex.VALUES:
            return Complex.VALUES[clean_name] + array

        if type_decl.type == "generic_type":
            clean_name = type_decl.child(0).text.decode()
            arguments = type_decl.child(1)
            match clean_name:
                case "List":
                    if arguments.child_count == 0:
                        return f"readParcelable{array}:java.util.List"

                    ref_ty = arguments.named_child(0).text.decode()
                    if ref_ty in Complex.VALUES:
                        return f"readList:{Complex.VALUES[ref_ty]}"
                    idef = compiler.get_import(ref_ty)
                    return f"readList:{idef.qname}"

                case "ParceledListSlice":
                    if arguments.child_count == 0:
                        return f"readParcelable{array}:android.app.ParceledListSlice"

                    ref_ty = arguments.named_child(0).text.decode()
                    if ref_ty in Complex.VALUES:
                        return f"readParceledListSlice:{Complex.VALUES[ref_ty]}"
                    idef = compiler.get_import(ref_ty)
                    return f"readParceledListSlice:{idef.qname}"

                case _:
                    raise TypeError(
                        f"Unsupported generic type {type_decl.text.decode()!r}"
                    )

        # 3. Check if the type name is in the imports
        idef = compiler.get_import(clean_name)
        return f"readParcelable{array}:{idef.qname}"

    def _qname_from_creator_access(self, identifier: str, compiler: "Compiler") -> str:
        """Resolves the qualified name of a creator field."""
        target = identifier.split(".")
        if len(target) == 2:
            idef = compiler.get_import(target[0])
            qname = idef.qname
        else:
            idef = compiler.get_import(target[0])
            qname = ".".join([idef.qname] + target[1:-1])
        return qname

    def call_from_expr(self, expr: Node, tracker: str, compiler: "Compiler") -> str:
        method = compiler.get_method_call(expr, tracker)
        if method:
            # Either the qualifier is the Parcel object (tracker) or
            # it is defined as an argument.
            qualifier = txt(method.child_by_field_name("object"))
            name = txt(method.child_by_field_name("name"))
            raw_args = method.child_by_field_name("arguments")
            args = compiler.get_invocation_arguments(raw_args)
            if qualifier == tracker:
                # By default we just record the method name
                match name:
                    case "readTypedList":
                        target = args[1]
                        pass

                    case "readTypedObject":
                        target = args[0]
                        return f"readParcelable:{self._qname_from_creator_access(target, compiler)}"

                    case "createTypedArray":
                        target = args[0]
                        return f"readList:{self._qname_from_creator_access(target, compiler)}"
                    case _:
                        return name

            else:
                # The object is another CREATOR
                field = method.child_by_field_name("object")
                match field.type:
                    case Constants.FIELD_ACCESS:
                        target = txt(field.named_child(0))
                    case Constants.IDENTIFIER:
                        target = txt(field)
                idef = compiler.get_import(target)
                return f"readParcelable:{idef.qname}"

        return "..."

    def const_val_of(self, expr: Node, compiler: "Compiler") -> str:
        match expr.type:
            case Constants.IDENTIFIER:
                # Possibly a constant reference: try to resolve the value
                constant = txt(expr)
                if constant in compiler.info.members:
                    field = compiler.info.members[constant]
                else:
                    # try super classes
                    for name in compiler.info.extends + compiler.info.implements:
                        idef = compiler.get_import(name)
                        if not idef.unit:
                            try:
                                unit = compiler.loader.import_(idef.qname)[0]
                            except (ImportError, FileNotFoundError, ValueError):
                                return constant
                        else:
                            unit = idef.unit

                        p = Preprocessor(unit)
                        if constant in p.members:
                            field = p.members[constant]
                            break

                if not field:
                    return constant

                declarator = field.child_by_field_name("declarator")
                return self.const_val_of(declarator.child(2), compiler)

            case Constants.INTEGER_LITERAL:
                return int(txt(expr).strip("lL"))
            case Constants.HEX_INTEGER_LITERAL:
                return int(txt(expr).strip("lL"), 16)
            case Constants.OCTAL_INTEGER_LITERAL:
                return int(txt(expr).strip("lL"), 8)
            case Constants.BINARY_INTEGER_LITERAL:
                return int(txt(expr).strip("lL"), 2)
            case Constants.STRING_LITERAL | Constants.CHARACTER_LITERAL:
                return txt(expr)
            case Constants.TRUE:
                return True
            case Constants.FALSE:
                return False
            case Constants.NULL_LITERAL:
                return None
            case _:
                raise TypeError(f"Unsupported constant type {expr.type!r}")


class NodeVisitor:
    """A simple visitor class for traversing the AST.

    This class will be responsible for generating :class:`FieldDef` and
    :class:`ConditionDef` instances.
    """

    def __init__(self, compiler: "Compiler") -> None:
        self.compiler = compiler

    def visit(self, node: Node, tracker: str, index: int) -> t.List[FieldDef]:
        """
        Traverses the given node and returns a list of :class:`FieldDef`
        instances (optional).
        """
        func = getattr(self, f"visit_{node.type}", None)
        return func(node, tracker, index) or [] if func else []

    def visit_local_variable_declaration(
        self, expr: Node, tracker: str, index: int
    ) -> t.Optional[t.List[FieldDef]]:
        """Parse a local variable declaration and return a member definition."""
        if self.compiler.is_local_assignment(expr, tracker):
            # Local variable: we try to trace the value to the final field
            local_member = self.compiler.get_local_member(expr)
            member = self.compiler.trace_local(expr.parent, local_member)
            call = self.compiler.th.call_from_expr(expr, tracker, self.compiler)
            return [FieldDef(member, call)]

    def visit_assignment_expression(
        self, expr: Node, tracker: str, index: int
    ) -> t.List[FieldDef]:
        """Parse an assignment statement and return a member definitions."""
        # The assignment must explicitly contain the tracker
        if not self.compiler.is_target_assignment(expr, tracker):
            return []

        member = self.compiler.get_assigned_member(expr)
        # retrieve the target Parcel method call and add
        # the new member to the list
        call = self.compiler.th.call_from_expr(expr, tracker, self.compiler)
        return [FieldDef(member, call)]

    def visit_return_statement(
        self, expr: Node, tracker: str, index: int
    ) -> t.Optional[t.List[FieldDef]]:
        # Return statement with (possible) tracker as argument
        ctor = expr.named_child(0)
        if ctor.type != Constants.OBJ_CREATION_EXPR:
            # end the loop on other return statements
            raise StopIteration

        args = self.compiler.get_invocation_arguments(
            ctor.child_by_field_name("arguments")
        )
        if tracker in args:
            # NOTE: we assert here, that the constructor is defined
            ctor = self.compiler.info.get_parcel_constructor()
            ctor_tracker = self.compiler.resolve_parcel_tracker(ctor)  #
            # pylint: disable-next=protected-access
            return self.compiler._parse_parcelable_java(ctor, ctor_tracker)
        return None

    def visit_if_statement(
        self, expr: Node, tracker: str, index: int
    ) -> t.Optional[t.List[FieldDef]]:
        # we will trace if statements as they may contain additional
        # members
        # NOTE: this implementation will only follow simple IF statements
        # with a call to the Parcel instance. All other cases can't be
        # handled (at least not yet)
        cond: ConditionDef = self.compiler.parse_condition(expr, tracker)
        if cond:
            consequence = expr.child_by_field_name("consequence")
            alternative = expr.child_by_field_name("alternative")
            if consequence:
                # pylint: disable-next=protected-access
                cond.consequence = self.compiler._parse_parcelable_java(
                    consequence, tracker
                )
            if alternative:
                # pylint: disable-next=protected-access
                cond.alternative = self.compiler._parse_parcelable_java(
                    alternative.named_child(0), tracker
                )
            return [cond]
        return None

    def visit_method_invocation(
        self, expr: Node, tracker: str, index: int
    ) -> t.Optional[t.List[FieldDef]]:
        # If this statement is a delegate, we have to first parse
        # the invoked method.
        qualifier = txt(expr.child_by_field_name("object"))
        if qualifier == tracker:
            # the statement is a call to the current Parcel
            # object.
            call = self.compiler.th.call_from_expr(expr, tracker, self)
            return [FieldDef(tracker, call)]

        if self.compiler.is_delegate(expr, tracker):
            # We have two types of delegates:
            #   1. Delegate parsing to antother parcelable
            #   2. Delegate parsing to a local method
            if qualifier is not None:
                # try to resolve the type of the delegate
                if qualifier == "super":
                    # call to super class
                    idef = self.compiler.get_import(self.compiler.info.extends[0])
                    return [FieldDef("_super", f"readParcelable:{idef.qname}")]

                member_ty = self.compiler.info.members[qualifier].child_by_field_name(
                    "type"
                )
                call = self.compiler.th.call_of(member_ty, self.compiler)
                return [FieldDef(qualifier, call)]

            method = self.compiler.info.methods.get(
                txt(expr.child_by_field_name("name"))
            )
            if method is not None:
                method_tracker = self.compiler.resolve_parcel_tracker(method)
                # pylint: disable-next=protected-access
                return self.compiler._parse_parcelable_java(method, method_tracker)


class Compiler:
    """
    The _compiler_ class is used to translate given AIDL definitions into
    a pre-defined structure that can be used to decode and potentially
    encode data.

    The internal processing depends on which type the underlying unit was
    associated with. For instance, :code:`BINDER` declarations will result
    in a different output than parsed :code:`PARCELABLE_JAVA` declarations.

    In general, the compiler tries to describe what operations need to be
    performed on a :class:`Unit` in order to decode or encode data. There
    are predefined methods, which will be mapped to their Python equivalents:

    .. list-table::
        :header-rows: 1
        :widths: 20 80

        * - Method
          - Python Type
        * - readInt, readLong, readShort, readByte
          - int
        * - readBoolean
          - bool
        * - readString
          - str (:code:`utf-16-le` codec)
        * - readString8
          - str (:code:`utf-8` codec)
        * - readFloat, readDouble
          - float


    - Binder: All defined methods will be inspected and their parameters
      will be translated according to the scheme introduced before.

    :param unit: The unit to compile.
    :type unit: Unit
    :param loader: The :class:`BaseLoader` object to use.
    :type loader: BaseLoader
    """

    def __init__(
        self,
        unit: Unit,
        loader: BaseLoader,
        type_handler: t.Optional[TypeHandler] = None,
        visitor_cls: t.Type[NodeVisitor] = None,
    ) -> None:
        self.loader = loader
        # Calling the preprocessor will load defined members, methods and
        # constructors of the unit.
        self.info = Preprocessor(unit)
        self.th = type_handler or TypeHandler()
        # internal private fields
        self._imports = ImportDefList()
        self._visitor_ty = visitor_cls or NodeVisitor

    @property
    def unit(self) -> Unit:
        """Returns the current unit."""
        return self.info.unit

    @property
    def resolved_imports(self) -> ImportDefList:
        """Returns the list of resolved imports."""
        if len(self._imports) == 0:
            self._resolve_imports()
        return self._imports

    def compile(self) -> BinderDef | ParcelableDef:
        """Compiles the stored unit. (if possible)"""
        definition = None
        match self.unit.type:
            case Type.PARCELABLE_JAVA:
                definition = self.as_parcelable()
            case Type.BINDER:
                definition = self.as_binder()
            case _:
                raise TypeError(f"{self.unit.type} is not a supported type")

        self.loader.ucache[self.info.qname] = definition
        return definition

    def as_binder(self) -> BinderDef:
        """Returns the given unit as a :class:`BinderDef`."""
        if self.unit.type != Type.BINDER:
            raise TypeError(f"{self.unit.type} is not a binder class")

        bdef = BinderDef(self.info.qname, Type.BINDER.name, None)
        # at first, we have to import all the referenced classes,
        # because we need to know what type they are.
        self._resolve_imports()
        method_defs = set()
        for i, name in enumerate(self.info.methods, 1):
            method_decl = self.info.methods[name]
            rtype = method_decl.child_by_field_name("type")
            is_oneway = rtype.text == b"void"
            # NOTE: the method might not be oneway, BUT there may be arguments
            # with the modifier 'out', which can be decoded as well.
            # TODO: the transaction code might be different
            mdef = MethodDef(
                name=name,
                tc=i,
                oneway=is_oneway,
                retval=None if is_oneway else [],
                arguments=[],
            )
            if not is_oneway:
                mdef.retval.append(ReturnDef(self.th.call_of(rtype, self)))

            # each parameter may store different modifiers, which will be
            # expressed by the first unnamed node in the formal parameter
            # declaration
            parameters = get_parameters(
                method_decl, self.info.lang, "binder_formal_parameters"
            )
            for param_name, param_decl in parameters.items():
                # The 'in' modifier is inferred as default modifier
                param_modifier = get_parameter_modifier(param_decl)
                param_type = param_decl.child_by_field_name("type")
                is_out = param_modifier in ("out", "inout")
                pdef = ParameterDef(
                    name=param_name,
                    call=self.th.call_of(param_type, self),
                    direction=Direction[param_modifier.upper()],
                )
                if is_out:
                    if is_oneway:
                        mdef.retval = []
                    mdef.retval.append(pdef)

                if param_modifier in ("in", "inout"):
                    mdef.arguments.append(pdef)
            method_defs.add(mdef)

        bdef.methods = list(sorted(method_defs, key=lambda x: x.tc))
        self.loader.ucache[self.info.qname].body = bdef
        return bdef

    def as_parcelable(self) -> ParcelableDef:
        """Returns the given unit as a :class:`ParcelableDef`."""
        if self.unit.type not in (Type.PARCELABLE, Type.PARCELABLE_JAVA):
            raise TypeError(f"{self.unit.type} is not a parcelable class")

        pdef = ParcelableDef(self.info.qname, self.unit.type.name, None)
        self._resolve_imports()
        if self.unit.type == Type.PARCELABLE_JAVA:
            # We are using the CREATOR instance as our entry point
            # and will follow all method calls from there.
            ctor = self.info.get_parcel_constructor()
            creator = self.info.get_creator()
            if not (ctor or creator):
                raise UnsupportedTypeError(
                    f"No parcel constructor or creator found - {self.info.qname}"
                )

            target = creator or ctor
            tracker = self.resolve_parcel_tracker(target)
            pdef.fields = self._parse_parcelable_java(target, tracker)
        return pdef

    # --- internal helpers ---
    def get_import(self, qname: QName | str) -> ImportDef:
        """Returns the import with the given qualified name (or tries to import it)."""
        idef = self._imports.get(qname)
        if idef is not None:
            return idef

        try:
            for unit in self.loader.import_(qname):
                unit_qname = f"{unit.package}.{unit.name}"
                idef = ImportDef(qname, unit.type, unit)
                # import all other units
                self._imports.append(idef)
                if unit_qname == qname:
                    break
        except (ImportError, FileNotFoundError, ValueError):
            # try to search for inner classes
            scope = self.unit.body
            cls_decl = get_class_by_name(scope, qname, self.info.lang)
            if cls_decl:
                idef = ImportDef(
                    f"{self.info.qname}.{qname}", Type.PARCELABLE_JAVA, cls_decl
                )
            else:
                idef = ImportDef(qname)
            self._imports.append(idef)

        return idef

    def _resolve_imports(self) -> None:
        """Resolves all imports of the current unit."""
        if len(self._imports) > 0:
            return

        # 1. Import all specified types
        for imp in self.unit.imports:
            self.get_import(imp)

        # 2. Import all classes in the current directory
        decl_qname = get_declaring_class(self.info.qname)
        package, _ = decl_qname.rsplit(".", 1)

        rel_dir_path = package.replace(".", os.path.sep)
        abs_dir_path = self.loader.to_absolute(rel_dir_path)
        for fname in os.listdir(abs_dir_path):
            name, ext = os.path.splitext(fname)
            # We will only import AIDL files
            if ext in (FULL_AIDL_EXT):
                qname = f"{package}.{name}"
                self.get_import(qname)

    def resolve_parcel_tracker(self, method: Node) -> str:
        """Tries to retrieve the parameter name of the parcel argument"""
        parameters = get_parameters(method, self.info.lang)
        if len(parameters) < 1:
            raise ValueError(
                f"Invalid number of parameters to resolve parcel tracker - got {len(parameters)}"
            )
        return next(iter(parameters.keys()))

    # --- parcelable java ---
    def _parse_parcelable_java(
        self, method: Node, tracker: str
    ) -> t.List[FieldDef | ConditionDef]:
        """
        Processes the given method declaration and returns a list of
        all field definitions in the right order.
        """
        members = []
        visitor = self._visitor_ty(self)
        # We iterate over all statements in the body and look out
        # for delegations, assignments and local variables. The
        # 'body' of the method will always contain one child node,
        # which then stores all the statements.
        if method.type != Constants.BLOCK:
            body = method.child_by_field_name("body")
            if not body:
                # But if there are no statements in the body, we can
                # simply return an empty list
                return members
        else:
            body = method

        for idx, statement in enumerate(body.named_children):
            if statement.type == Constants.EXPR_STATEMENT:
                expr = statement.named_child(0)
            else:
                expr = statement

            try:
                members.extend(visitor.visit(expr, tracker, idx))
            except StopIteration:
                members.append(Stop())
                break

        return members

    def is_target_assignment(self, expr: Node, tracker: str) -> bool:
        """Check if an expression is an assignment with the tracker."""
        if not expr.type == Constants.ASSIGNMENT_EXPR:
            return False

        # The left operand must point to a member and the right
        # must be a method invocation.
        left = expr.named_child(0)
        right = self.get_method_call(expr.named_child(1), tracker)
        if not right:
            return False

        # TODO: handle cast_expression
        if right.type != Constants.METHOD_CALL or left.type not in (
            Constants.FIELD_ACCESS,
            Constants.IDENTIFIER,
        ):
            return False

        # The left operand must point to a member
        if left.type == Constants.IDENTIFIER:
            member_name = txt(left)
            if not member_name in self.info.members:
                return False
        else:
            member_name = txt(left.named_child(1))
            if (
                left.named_child(0).type != "this"
                and member_name not in self.info.members
            ):
                return False

        # the assignment may be a call to another CREATOR, therefore
        # the qualifier or first parameter can be the value of the
        # tracker.
        if txt(right.child_by_field_name("object")) == tracker:
            return True

        args = self.get_invocation_arguments(right.child_by_field_name("arguments"))
        return tracker in args

    def get_invocation_arguments(self, invocation: Node) -> t.List[str]:
        return [x.text.decode() for x in invocation.named_children]

    def get_assigned_member(self, expr: Node) -> str:
        """
        Returns the name of the member that is assigned to.
        """
        assert expr.type == Constants.ASSIGNMENT_EXPR
        # The left operand must point to a member
        left = expr.named_child(0)
        if left.type == Constants.IDENTIFIER:
            return txt(left)

        return txt(left.child_by_field_name("field"))

    def parse_condition(self, expr: Node, tracker: str) -> t.Optional[ConditionDef]:
        """Parse an if statement and return a condition definition."""
        if expr.type != Constants.IF_STATEMENT:
            return None

        condition = expr.named_child(0)
        # Currently, only binary expressions are accepted
        if condition.type != Constants.PARENTHESIZED_EXPR:
            return None

        binary_expr = condition.named_child(0)
        if binary_expr.type != Constants.BINARY_EXPR:
            return None

        left = binary_expr.named_child(0)
        right = binary_expr.named_child(1)
        for child in [left, right]:
            if child.type != Constants.METHOD_CALL:
                continue

            qualifier = txt(child.child_by_field_name("object"))
            if qualifier != tracker:
                continue

            const_val = left if child is right else right
            name = txt(child.child_by_field_name("name"))
            op = txt(binary_expr.child(1))
            return ConditionDef(
                name, self.th.const_val_of(const_val, self), op, None, None
            )

        return None

    def is_delegate(self, expr: Node, tracker: str) -> bool:
        """Check if a method is a delegate to another internal method (not constructor)"""
        args = self.get_invocation_arguments(expr.child_by_field_name("arguments"))
        return len(args) == 1 and args[0] == tracker

    def get_method_call(self, expr: Node, tracker: str) -> t.Optional[Node]:
        """Tries to resolve a method invocation node from the given start node."""
        query = self.info.lang.query(f"({Constants.METHOD_CALL}) @func")
        results = query.captures(expr)
        for invocation, _ in results:
            if txt(invocation.child_by_field_name("object")) == tracker:
                return invocation

            raw_args = invocation.child_by_field_name("arguments")
            if raw_args and tracker in self.get_invocation_arguments(raw_args):
                return invocation

        return None

    def is_local_assignment(self, expr: Node, tracker: str) -> bool:
        """Check if an expression is a local assignment with the tracker."""
        if expr.type != Constants.LOCAL_VAR_DECL:
            return False

        # The left operand must point to a member and the right
        # must be a method invocation.
        declarator = expr.named_child(1)
        method = self.get_method_call(declarator, tracker)
        if not method:
            return False

        # the assignment may be a call to another CREATOR, therefore
        # the qualifier or first parameter can be the value of the
        # tracker.
        if txt(method.child_by_field_name("object")) == tracker:
            return True

        args = self.get_invocation_arguments(method.child_by_field_name("arguments"))
        return tracker in args

    def get_local_member(self, expr: Node) -> t.Optional[str]:
        """Returns the name of the member that is assigned to."""
        if expr.type != Constants.LOCAL_VAR_DECL:
            return None

        return txt(expr.named_child(1).named_child(0))

    def trace_local(self, body: Node, tracker: str) -> str:
        query = self.info.lang.query(f"({Constants.ASSIGNMENT_EXPR}) @assignment")
        query2 = self.info.lang.query(f"({Constants.IDENTIFIER}) @field")
        results = query.captures(body)
        for assignment, _ in results:
            for identifier, _ in query2.captures(assignment.named_child(1)):
                if txt(identifier) == tracker:
                    field = assignment.named_child(0)
                    if field.type == Constants.FIELD_ACCESS:
                        return txt(field.child_by_field_name("field"))
                    return txt(field)

        return tracker
