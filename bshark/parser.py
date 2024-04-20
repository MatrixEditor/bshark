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
import struct
import typing as t

from caterpillar.context import Context, this, CTX_STREAM
from caterpillar.fields import *
from caterpillar._common import WithoutContextVar

from bshark.compiler import BaseLoader, BinderDef
from bshark.compiler.model import UnsupportedTypeError, Direction


def _align(n: int, context: Context) -> int:
    pos = context[CTX_STREAM].tell()
    idx = pos % n
    if idx:
        context[CTX_STREAM].read(n - idx)


@singleton
class string16(String):
    def __init__(self):
        super().__init__(..., encoding="utf-16-le")

    def __size__(self, context) -> int:
        return (uint32.unpack_single(context) * 2) + 2

    def unpack_single(self, context) -> str:
        val = super().unpack_single(context).strip("\x00")
        pos = context[CTX_STREAM].tell()
        _align(4, context)
        return val


string8 = Prefixed(uint32, encoding="utf-8")
char16 = String(4, encoding="utf_16_le")


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
            call = argument.call
            func = getattr(self, call, None)
            if not func:
                raise ValueError(f"Unknown call {call!r}")
            setattr(data, argument.name, func(argument, context))

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
        return int16.unpack_single(context)

    def readChar(self, arg, context) -> str:
        return char16.unpack_single(context)

    def readString(self, arg, context) -> str:
        return string16.__unpack__(context)

    def readString8(self, arg, context) -> str:
        val = string8.unpack_single(context)
        context[CTX_STREAM].read(1)  # terminator
        _align(4, context)
        return val

    readBoolean = readUInt

    def readByte(self, arg, context) -> int:
        val = uint8.unpack_single(context)
        _align(4, context)
        return val

    def readStrongBinder(self, arg, context) -> Context:
        obj = Context(
            type=uint32.unpack_single(context),
            flags=uint32.unpack_single(context),
            handle=uint64.unpack_single(context),
            cookie=uint64.unpack_single(context),
        )
        if context._root.android_version > 9:
            obj.status = uint32.unpack_single(context)
        return obj
