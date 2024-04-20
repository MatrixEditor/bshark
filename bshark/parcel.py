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
import enum

from caterpillar.shortcuts import struct, LittleEndian, ctx
from caterpillar.fields import uint32, Memory, Enum, singleton, String, Computed

from bshark.parser import Parser
from bshark.compiler.model import Direction


@singleton
class string16(String):
    def __init__(self):
        super().__init__(..., encoding="utf-16-le")

    def __size__(self, context) -> int:
        return uint32.unpack_single(context) * 2


class Environment(enum.IntEnum):
    SYST = int.from_bytes(b"TSYS", "little")
    # TODO


def parse_incoming_message(data: memoryview, context):
    parser_cls = getattr(context._root, "parser_cls", Parser)
    context.direction = Direction.IN
    return parser_cls(data)


@struct(order=LittleEndian)
class IncomingMessage:
    # The first fields define the interface token for the message,
    # which is later used to identify the binder interface.

    smp: uint32
    """Strict Mode Policy"""

    with ctx._root.android_version >= 11:
        # Some fields should be parsed only if the Android
        # version is 11 or higher.
        work_suid: uint32
        """Work Source UID"""

        env: Enum(Environment, uint32)
        """Environment"""

    with ctx._root.android_version == 10:
        work_suid: uint32
        """Work Source UID"""

    descriptor: string16
    """Interface token descriptor"""

    data: Memory(...) >> parse_incoming_message
    """All following data"""


def parse_outgoing_message(data: memoryview, context):
    parser_cls = getattr(context._root, "parser_cls", Parser)
    context.direction = Direction.OUT
    return parser_cls(data)


@struct
class OutgoingMessage:
    descriptor: Computed(ctx._root.interface)
    data: Memory(...) >> parse_outgoing_message


