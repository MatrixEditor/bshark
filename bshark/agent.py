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
import frida
import threading

from bshark.compiler import BaseLoader

SCRIPT_DIR = os.path.dirname(os.path.realpath(__file__))
AGENT_SCRIPT = os.path.join(SCRIPT_DIR, "agent.js")

MessageCallback = t.Callable[[dict, bytes], None]


class TransactionListener:
    def on_transaction(self, code: int, data: bytes) -> None:
        pass

    def on_reply(self, code: int, interface: str, data: bytes) -> None:
        pass


class Agent:
    def __init__(
        self,
        loader: BaseLoader,
        android_version: int,
        device: frida.core.Device,
        *msg_callbacks: MessageCallback,
        listener: TransactionListener,
        **kwargs,
    ) -> None:
        self.device = device
        self.android_version = android_version
        self.loader = loader
        self.listener = listener
        self.kwargs = kwargs
        with open(AGENT_SCRIPT, "r", encoding="utf-8") as f:
            self.base_script = f.read()

        # internal variables
        self.session = None
        self.pid = None
        self.script = None
        self._resume = False
        self.message_callbacks = msg_callbacks

        # threading states
        self._stop = threading.Event()
        self._thread = None

    def build_script(self, extra: t.List[str] = None) -> str:
        base = [self.base_script]
        for extra_script in extra or []:
            if not os.path.exists(extra_script):
                raise FileNotFoundError(f"{extra_script} not found")
            with open(extra_script, "r", encoding="utf-8") as f:
                base.append(f.read())
        return "\n".join(base)

    def stop(self):
        self._stop.set()
        if self._thread:
            self._thread.join()

    def spawn(
        self,
        program: str,
        extra: t.List[str] = None,
    ) -> None:
        self.pid = self.device.spawn([program])
        self._resume = True
        self.attach(self.pid, extra)

    def attach(self, pid: int, extra: t.List[str] = None) -> None:
        if not self.pid:
            self.pid = pid
        self.session = self.device.attach(self.pid)
        self.script = self.session.create_script(self.build_script(extra))
        self.script.on("message", self._on_message)
        for cb in self.message_callbacks:
            self.script.on("message", cb)

        self._thread = threading.Thread(target=self._run)
        self._thread.start()

    def _run(self) -> None:
        self.script.load()
        if self._resume:
            self.device.resume(self.pid)
        # Configure the android version to use
        self.script.exports.configure(
            None, {"version": self.android_version, **self.kwargs}
        )
        self._stop.wait()
        self.session.detach()

    def _on_message(self, msg: dict, data: bytes) -> None:
        if msg.get("type") != "send":
            return

        payload = msg.get("payload")
        if not payload:
            return

        code = payload.get("code")
        descriptor = payload.get("descriptor")
        transaction_type = payload.get("type")
        match transaction_type:
            case "bshark_transaction_reply":
                self.listener.on_reply(code, descriptor, data)
            case "bshark_transaction_start":
                self.listener.on_transaction(code, data)
            case _:
                # maybe throw an exception here
                pass
