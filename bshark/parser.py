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

        interface: BinderDef = units[0].body
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
