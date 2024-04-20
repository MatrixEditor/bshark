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

from caterpillar.context import Context, this

from bshark.compiler import BaseLoader, BinderDef
from bshark.compiler.model import UnsupportedTypeError


class Parser:
    def __init__(self, data: memoryview, loader: t.Optional[BaseLoader] = None) -> None:
        self.data = data
        self.loader = loader

    def __unpack__(self, context: Context) -> None:
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
        mdef = next(filter(lambda x: x.tc == code, interface.methods), None)
        if not mdef:
            raise RuntimeError(
                f"Method with transaction code {code!r} in {qname!r} not found"
            )

        for argument in mdef.arguments:
            call = argument.call
            # TODO: global mapping for parcel
        return mdef
