.. _api-compiler-model:

Model Classes and API
=====================

.. automodule:: bshark.compiler.model

Public Type Aliases
-------------------

.. autoattribute:: bshark.compiler.model.QName

    Qualified class name. This is a string of the form :code:`package.ClassName`.

.. autoattribute:: bshark.compiler.model.RPath

    Relative path. This is a string of the form :code:`path/to/file.ext`.

.. autoattribute:: bshark.compiler.model.ABSPath

    Absolute path. This is a string of the form :code:`/src-root/path/to/file.ext`.

.. autoattribute:: bshark.compiler.model.QImport

    Qualified import.  This is a string of the form :code:`package.ClassName` with
    an optional wildcard to import everything.


Public Types
------------

.. autoclass:: bshark.compiler.model.FieldDef
    :members:
    :undoc-members:

.. autoclass:: bshark.compiler.model.Direction
    :members:
    :undoc-members:

.. autoclass:: bshark.compiler.model.ReturnDef
    :members:
    :undoc-members:

.. autoclass:: bshark.compiler.model.ParameterDef
    :members:
    :undoc-members:

.. autoclass:: bshark.compiler.model.MethodDef
    :members:
    :undoc-members:

.. autoclass:: bshark.compiler.model.ImportDef
    :members:
    :undoc-members:

.. autoclass:: bshark.compiler.model.ConditionDef
    :members:
    :undoc-members:

.. autoclass:: bshark.compiler.model.ClassDef
    :members:
    :undoc-members:

.. autoclass:: bshark.compiler.model.ParcelableDef
    :members:
    :undoc-members:
    :show-inheritance:

.. autoclass:: bshark.compiler.model.BinderDef
    :members:
    :undoc-members:
    :show-inheritance:

.. autoclass:: bshark.compiler.model.Stop

.. autoclass:: bshark.compiler.model.ImportDefList
    :members:
    :undoc-members:

Public interface
----------------

.. autofunction:: bshark.compiler.model.to_json

.. autofunction:: bshark.compiler.model.from_json


Internal Types
--------------

.. autoclass:: bshark.compiler.model.UnsupportedTypeError

.. autoclass:: bshark.compiler.model.Primitive

.. autoclass:: bshark.compiler.model.Complex




