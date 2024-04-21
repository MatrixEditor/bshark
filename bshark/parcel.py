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
import typing as t

from caterpillar.shortcuts import struct, LittleEndian, ctx, unpack, this
from caterpillar.fields import *

from bshark.parser import Parser, string16
from bshark.compiler import BaseLoader
from bshark.compiler.model import Direction



class Environment(enum.IntEnum):
    #: Default Android device environment
    SYST = int.from_bytes(b"TSYS", "little")

    #: Android VNDK (Vendor Native Development Kit)
    VNDK = int.from_bytes(b"VNDK", "little")

    #: Recovery mode
    RECO = int.from_bytes(b"RECO", "little")

    #: unknown mode
    UNKN = int.from_bytes(b"UNKN", "little")


def parse_incoming_message(data: memoryview, context):
    parser_cls = getattr(context._root, "parser_cls", None)
    context.direction = Direction.IN
    return (parser_cls or Parser)(data)


@struct(order=LittleEndian)
class IncomingMessage:
    # The first fields define the interface token for the message,
    # which is later used to identify the binder interface.

    smp: uint32
    """Strict Mode Policy"""

    with If(ctx._root.android_version >= 11):
        # Some fields should be parsed only if the Android
        # version is 11 or higher.
        work_suid: uint32
        """Work Source UID"""

        env: Enum(Environment, uint32)
        """Environment"""

    with ElseIf(ctx._root.android_version == 10):
        work_suid: uint32
        """Work Source UID"""

    descriptor: string16
    """Interface token descriptor"""

    data: Memory(...) >> parse_incoming_message
    """All following data"""


def parse_outgoing_message(data: memoryview, context):
    parser_cls = getattr(context._root, "parser_cls", None)
    context.direction = Direction.OUT
    return (parser_cls or Parser)(data)


@struct(order=LittleEndian)
class OutgoingMessage:
    #: The first fields define the interface token for the message,
    #: which is later used to identify the binder interface. It MUST
    #: be provided through the 'unpack' call.
    descriptor: Computed(ctx._root.interface)

    #: The first four bytes specify whether an error occurred during
    #: the transaction.
    error_code: int32
    error: this.error_code >> {
        # By default, just return the error code
        DEFAULT_OPTION: ctx._value
    }

    with this.error == 0:
        # The outgoing message will be parsed only if the error code
        # is not set.
        data: Memory(...) >> parse_outgoing_message


def parse(
    data: memoryview,
    code: int,
    loader: BaseLoader,
    version: int,
    descriptor: t.Optional[str] = None,
    in_: bool = True,
    parser_cls: t.Optional[t.Type[Parser]] = None,
) -> IncomingMessage | OutgoingMessage:
    """
    Parses an incoming or outgoing message based on the given parameters.

    :param data: the received transaction data
    :type data: memoryview
    :param code: the transaction code
    :type code: int
    :param loader: the loader instance
    :type loader: BaseLoader
    :param version: the configured android version
    :type version: int
    :param descriptor: an optional interface descriptor, defaults to None,
                       required for outgoing messages
    :type descriptor: t.Optional[str], optional
    :param in_: whether the message is incoming, defaults to True
    :type in_: bool, optional
    :return: the parsed message
    :rtype: IncomingMessage | OutgoingMessage
    """
    return unpack(
        IncomingMessage if in_ else OutgoingMessage,
        data,
        code=code,
        loader=loader,
        android_version=version,
        interface=descriptor,
        parser_cls=parser_cls,
    )
