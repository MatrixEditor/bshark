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
"""
*bshark's* parsing architecture relies on function implementations for each
corresponding Parcel method. For instance, the AIDL definition specifies
to call :code:`readInt`, where :code:`readInt` would be a function in the
used :class:`Parser` instance.

It is also possible to extend the current parser to support even more
methods by subclassing it and simply defining the new methods. For example,

.. code-block:: python
    :linenos:

    from bshark.parser import Parser

    class MyParser(Parser):
        def readInt(self, arg, context):
            return self.data.read(4)
"""


import io
import functools
import typing as t

from caterpillar.context import Context, this, CTX_STREAM

# pylint: disable-next=unused-wildcard-import,wildcard-import
from caterpillar.fields import *
from caterpillar._common import WithoutContextVar

from bshark.compiler import BaseLoader, BinderDef, ParcelableDef
from bshark.compiler.model import UnsupportedTypeError, Direction, Stop
from bshark.compiler.model import FieldDef, ParameterDef, ConditionDef


def _align(
    n: int, context: Context, func: t.Optional[t.Callable[[Context], int]] = None
) -> t.Optional[t.Any]:
    """
    Aligns the current position of the stream in the context to
    the nearest multiple of :code:`n`.

    This function calculates the current position of the stream in
    the context and aligns it to the nearest multiple of :code:`n`.
    It then adjusts the stream position accordingly. If the current
    position is already aligned, no action is taken.

    :param n: the alignment
    :type n: int
    :param context: the current context
    :type context: Context
    """
    rval = func(context) if func else None
    pos = context[CTX_STREAM].tell()
    idx = pos % n
    if idx:
        context[CTX_STREAM].read(n - idx)
    return rval


@singleton
class string16(String):
    def __init__(self):
        super().__init__(..., encoding="utf-16-le")

    def __size__(self, context) -> int:
        return (uint32.unpack_single(context) * 2) + 2

    def unpack_single(self, context) -> str:
        # NOTE: We have to align the content here and not using
        # _align(..., string16.__unpack__), because this struct
        # is used within the IncomingMessage class definition
        rval = super().unpack_single(context).strip("\x00")
        _align(4, context)
        return rval


string8 = Prefixed(int32, encoding="utf-8")


class Parser:
    """A simple parser class to handle incoming or outgoing messages.

    :param data: the data to parse
    :type data: memoryview
    :param loader: the loader to use, defaults to None
    :type loader: t.Optional[BaseLoader], optional
    """

    def __init__(self, data: memoryview, loader: t.Optional[BaseLoader] = None) -> None:
        self.data = io.BytesIO(data.obj)
        self.loader = loader

    def __pack__(self, obj, context):
        raise NotImplementedError("Currently not supported")

    def __unpack__(self, context: Context) -> Context:
        if not self.loader:
            # The loader may be set in the root context if not
            # specified in the contructor call
            try:
                self.loader = context._root.loader
            except AttributeError as err:
                raise ValueError("No loader specified") from err

        qname = this.descriptor(context)
        units = self.loader.import_(qname)
        if not units or not isinstance(units[0], BinderDef):
            raise UnsupportedTypeError(
                f"Only compiled binder definitions are supported (at {qname!r})"
            )

        interface: BinderDef = units[0]
        # The transaction code will be stored in the root context
        code = context._root.code
        with WithoutContextVar(context, CTX_STREAM, self.data):
            match context.direction:  # is set in the current context
                case Direction.IN:
                    return self.parse_in(interface, code, context)
                case Direction.OUT:
                    return self.parse_out(interface, code, context)
                case _:
                    raise ValueError(f"Unknown direction {context.direction!r}")

    def parse_in(self, bdef: BinderDef, code: int, context: Context) -> Context:
        """Parses an incoming message.

        :param bdef: the interface definition
        :type bdef: BinderDef
        :param code: the current transaction code
        :type code: int
        :param context: the current context
        :type context: Context
        """
        mdef = next(filter(lambda x: x.tc == code, bdef.methods), None)
        if not mdef:
            raise ValueError(
                f"Method with transaction code {code!r} in {bdef.qname!r} not found"
            )

        data = Context()
        for argument in mdef.arguments:
            try:
                val = self.read_data(argument, context)
                if isinstance(val, tuple):
                    # multiple values returned
                    for name, v in val:
                        setattr(data, name, v)
                else:
                    setattr(data, argument.name, val)
            except StopIteration:
                break
            except Exception as err:  # pylint: disable=broad-exception-caught
                data._error = err
                break

        leftover = self.data.read()
        if leftover:
            data._leftover = leftover
        return data

    def parse_out(self, bdef: BinderDef, code: int, context: Context) -> Context:
        """Parses an outgoing message.

        :param bdef: the interface definition
        :type bdef: BinderDef
        :param code: the current transaction code
        :type code: int
        :param context: the current context
        :type context: Context
        """
        pass

    def read_data(
        self, arg: FieldDef | ConditionDef | ParameterDef, context: Context
    ) -> t.Any | t.Tuple[t.Tuple[str, t.Any]]:
        """Reads data from the stream.

        :param arg: the argument
        :type arg: FieldDef | ConditionDef | MethodDef
        :param context: the current context
        :type context: Context
        :return: the parsed data
        :rtype: t.Any
        """
        if isinstance(arg, Stop):
            raise StopIteration()

        call = arg.call
        is_typed = ":" in call
        if is_typed:
            call, name = call.split(":")

        func = getattr(self, call, None)
        if not func:
            raise ValueError(f"Unknown call {call!r}")

        val = func(arg, context) if not is_typed else func(arg, context, name=name)
        match arg:
            case ParameterDef() | FieldDef():
                return val

            case ConditionDef():
                result = []
                target = arg.consequence if bool(val) else arg.alternative
                for field in target:
                    result.append((field.name, self.read_data(field, context)))
                return tuple(result)

            case _:
                raise ValueError(f"Unknown call {call!r} for {arg!r}")

    def read_object(
        self,
        fields: t.Iterable[FieldDef | ConditionDef | ParameterDef],
        context: Context,
    ) -> Context:
        """Creates an object from the given fields.

        :param fields: the fields of the object to create
        :type fields: t.Iterable[FieldDef | ConditionDef | ParameterDef]
        :param context: the current context
        :type context: Context
        :return: the parsed object
        :rtype: Context
        """
        result = Context()
        for field in fields:
            try:
                val = self.read_data(field, context)
            except StopIteration:
                break
            if isinstance(val, tuple):
                for name, v in val:
                    result[name] = v
            else:
                result[field.name] = v
        return result

    # --- primitive methods ---
    def readInt(self, arg, context) -> int:
        return int32.unpack_single(context)

    def readUInt(self, arg, context) -> int:
        return uint32.unpack_single(context)

    def readFloat(self, arg, context) -> float:
        return float32.unpack_single(context)

    def readDouble(self, arg, context) -> float:
        return float64.unpack_single(context)

    def readLong(self, arg, context) -> int:
        return int64.unpack_single(context)

    def readULong(self, arg, context) -> int:
        return uint64.unpack_single(context)

    def readShort(self, arg, context) -> int:
        return _align(4, context, int16.unpack_single)

    def readChar(self, arg, context) -> str:
        return chr(int32.unpack_single(context))

    def readString(self, arg, context) -> str:
        # already aligned
        # pylint: disable-next=no-value-for-parameter
        return string16.__unpack__(context)

    def readString8(self, arg, context) -> str:
        val = string8.unpack_single(context)
        context[CTX_STREAM].read(1)  # terminator
        _align(4, context)
        return val

    def readBoolean(self, arg, context) -> bool:
        return bool(self.readInt(arg, context))

    def readByte(self, arg, context) -> int:
        return _align(4, context, uint8.unpack_single)

    def readByteUnaligned(self, arg, context) -> int:
        return uint8.unpack_single(context)

    def readStrongBinder(self, arg, context) -> Context:
        # taken from struct flat_binder_object in binder.h
        obj = Context(
            type=uint32.unpack_single(context),
            flags=uint32.unpack_single(context),
            handle=uint64.unpack_single(context),
            cookie=uint64.unpack_single(context),
        )
        if context._root.android_version > 9:
            obj.status = uint32.unpack_single(context)
        return obj

    def readByteVector(self, arg, context) -> t.List[int]:
        return self._read_vector(arg, context, self.readByteUnaligned)

    def readIntVector(self, arg, context) -> t.List[int]:
        return self._read_vector(arg, context, self.readInt)

    def readLongVector(self, arg, context) -> t.List[int]:
        return self._read_vector(arg, context, self.readLong)

    def readFloatVector(self, arg, context) -> t.List[float]:
        return self._read_vector(arg, context, self.readFloat)

    def readDoubleVector(self, arg, context) -> t.List[float]:
        return self._read_vector(arg, context, self.readDouble)

    def readStringVector(self, arg, context) -> t.List[str]:
        return self._read_vector(arg, context, self.readString)

    def readBooleanVector(self, arg, context) -> t.List[bool]:
        return self._read_vector(arg, context, self.readBoolean)

    def readCharVector(self, arg, context) -> t.List[str]:
        return self._read_vector(arg, context, self.readChar)

    def readParcelable(
        self, arg, context, name: t.Optional[str] = None
    ) -> t.Optional[Context]:
        status = self.readInt(arg, context)
        if status != 1:
            return None

        if not name:
            name = self.readString(arg, context)

        # The specified name must have an equivalent in the cache of
        # the loader or we can't decode it.
        pdef: ParcelableDef = self.loader.ucache[name]
        return self.read_object(pdef.fields, context)

    def readParcelableVector(self, arg, context, name: str) -> t.List[Context]:
        size = self.readInt(arg, context)
        return [self.readParcelable(arg, context, name) for _ in range(size)]

    # --- private methods ---
    def _read_vector(self, arg, context, func) -> t.List[t.Any]:
        size = self.readInt(arg, context)
        return [func(arg, context) for _ in range(size)]
