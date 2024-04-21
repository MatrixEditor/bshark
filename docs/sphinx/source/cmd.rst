.. _cmd:

CLI Reference and Usage
=======================

Compiling AIDL
--------------

.. code-block:: bash

    python3 -m bshark.compiler -I $ANDROID_SRC compile $CLASS_NAME --output $OUTPUT_DIR

This will generate a JSON file with the qualified class name (e.g. :code:`com.example.SomeClass`) in the :code:`OUTPUT_DIR`
directory. The structure depends on the input class (either an interface or a parcelable
declaration):

.. tab-set::

    .. tab-item:: interface

        .. code-block:: json
            :linenos:

            {
                "name": "com.example.SomeClass",
                "methods": [
                    {
                        "name": "someMethod",
                        "tc": 1,
                        "oneway": true,
                        "retval": null,
                        "arguments": [
                            {
                                "name": "someArg",
                                "call": "readInt",
                                "direction": 0
                            }
                        ]
                    }
                ]

    .. tab-item:: parcelable

        .. code-block:: json
            :linenos:

            {
                "name": "com.example.SomeClass",
                "type": "PARCELABLE_JAVA",
                "fields": [
                    {
                        "name": "someField",
                        "call": "readInt"
                    }
                ]
            }


.. note::
    AIDL files must be in the :code:`$ANDROID_SRC` directory, which can be downloaded from the
    Android Open Source Repository. For instance, the input name :code:`com.example.SomeClass.json`
    should be located in :code:`$ANDROID_SRC/com/example/SomeClass.[aidl|java|json]`.

Batch Compilation
-----------------

.. code-block:: bash

    python3 -m bshark.compiler -I $ANDROID_SRC batch-compile -o $OUTPUT_DIR --recursive --force

This will generate a JSON file for **ALL** AIDL files in the :code:`$ANDROID_SRC` directory
under the :code:`$OUTPUT_DIR` directory. Note that this command tires to import all previously
compiled AIDL files from the output directory first.

Inspecting AIDL files
---------------------

.. code-block:: bash

    python3 -m bshark.compiler -I $ANDROID_SRC info $CLASS_NAME

This will print the various information about the loaded AIDL file including the internal parsed
file and defined data. For example:

.. code-block:: bash

    python3 -m bshark.compiler -I $ANDROID_SRC info android.accounts.Account
    Units of android.accounts.Account
    └── android.accounts.Account
        ├── Methods: 8
        ├── Constructors: 4
        ├── Members: 7
        ├── Compiled: False
        ├── Parcelable
        │   ├── Creator: True
        │   └── Ctor: True
        └── Info
            ├── QName: 'android.accounts.Account'
            ├── RPath: 'android/accounts/Account.java'
            └── Lang: 'java'


Decoding Transactions
---------------------

*There is currently no CLI support for decoding transaction messages*. The internal
parser will try to decode as much details as poosible from the received data.

.. code-block:: python
    :linenos:
    :caption: Decode a single message from received bytes

    import frida

    from caterpillar.shortcuts import unpack

    from bshark.agent import TransactionListener, Agent
    from bshark.parcel import IncomingMessage, OutgoingMessage

    loader = ... # you have to import all JSON files first

    class MyListener(TransactionListener):
        def on_transaction(self, code: int, data: bytes):
            # transaction started
            msg = unpack(
                IncomingMessage,
                data,
                android_version=..., # the version of the Android OS
                code=code,           # the code of the transaction
                loader=loader        # the global loader instance (with all cached structs)
            )
            # ...

        def on_reply(self, code: int, interface: str, data: bytes):
            reply = unpack(
                OutgoingMessage,
                data,
                android_version=..., # the version of the Android OS
                code=code,           # the code of the transaction
                loader=loader        # the global loader instance (with all cached structs)
                interface=interface  # the name of the interface
            )
            # ...

    device: frida.core.Device = ...
    agent = Agent(
        loader,
        android_version=...,  # the version of the Android OS
        device=device,        # the device to attach to
        listener=MyListener() # the transaction listener
    )

    # either spawn an app or attach to an existing process
    pid = ...
    agent.attach(pid)
    # or
    agent.spawn('com.example.app')