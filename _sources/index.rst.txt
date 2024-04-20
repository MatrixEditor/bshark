Welcome to bshark's documentation!
==================================

*bshark* is a Python library that provides an interface to capturing
and processing Android Binder transactions as well as compiling AIDL
files into struct definitions.

.. toctree::
    :maxdepth: 1
    :hidden:

    cmd.rst
    api/index.rst

.. grid:: 1 2 3 2

    .. grid-item-card:: CLI
      :link: cmd.html

      Command reference and usage explanation.


    .. grid-item-card:: API
      :link: api/index.html

      Source Code documentation and Library internals.


Installation
------------

Currently, there is no python package available for *bshark*. Therefore,
you have to use the GIT installation candidate:

.. code-block:: bash

    pip install bshark@git+https://github.com/MatrixEditor/bshark.git


Setup & Requirements
--------------------

What you will need to install *bshark*:

* At least Python 3.12 and the Python developer module
* A compiler that supports C11
* *receiving messages*: frida and an Android device (or emulator)

In order to compile AIDL files you will have to download the Android Source Code
(not the repository) of your required version. For example, we want to compile
all the AIDL files of the Android 11.0.0 API level (framework classes). Therefore,
you have to download :code:`frameworks/base` from `GoogleSource <https://android.googlesource.com/platform/frameworks/base/>`_.
In our case, we just need to download the Java source code, so downloading :code:`android11-d1-release/core/java/android.tar.gz`
will do the job. Once extracted, it can be used within the compile commands.


