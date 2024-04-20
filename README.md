# :shark: bshark

*bshark* is a Python library that provides an interface to capturing
and processing Android Binder transactions as well as compiling AIDL
files into struct definitions.

## Installation

Currently, there is no python package available for *bshark*. Therefore,
you have to use the GIT installation candidate:

```bash
pip install bshark@git+https://github.com/MatrixEditor/bshark.git
```

Please follow the documentation on how to use this library.

## Examples

### Compiling an AIDL file:
```python
from bshark.compiler import BaseLoader, Compiler, ParcelableDef

# More information about the Java sources are given in the
# documentation
loader = BaseLoader(['/path/to/android-java-root/'])
units  = loader.import_("android.accounts.Account")

c = Compiler(units[0], loader)
pdef: ParcelableDef = c.compile()
```

or using the command line interface:
```bash
python3 -m bshark.compiler         \ # base command
    -I /path/to/android-java-root/ \ # include directories
    compile                        \ # action
    -o /path/to/output/            \ # output directory
    android.accounts.Account       \ # target class to compile (AIDL file required)
```

### Capturing Binder transactions:
In order to receive binder transactions, we have to use a custom
`TransactionListener`, which wil be used later on by an `Agent`.
```python
from bshark.agent import TransactionListener
from bshark.parcel import parse, IncomingMessage, OutgoingMessage

loader = ... # the loader must store compiled Parcelable definitions

class MyListener(TransactionListener):
    def on_transaction(self, code: int, data: bytes) -> None:
        msg: IncomingMessage = parse(
            data,           # recevied data
            code,           # transaction code
            loader,         # loader
            version=...,    # Android API version
        )

    def on_reply(self, code: int, interface: str, data: bytes):
        msg: OutgoingMessage = parse(
            data,           # recevied data
            code,           # transaction code
            loader,         # loader
            version=...,    # Android API version
            descriptor=interface, # target interface
            in_=False
        )
```

With the listener, we can now capture transactions using an agent object:
```python
from bshark.agent import Agent

device = ... # aquire device object from frida
agent = Agent(
    loader,
    android_version=..., # Android API version
    device=device,       # the device to use
    listener=MyListener(),
)

# either spawn an application or attach to the pid
pid = ...
agent.attach(pid)
# or
agent.spawn('com.example.app', extras=["/path/to/my-extra-script.js"])

```