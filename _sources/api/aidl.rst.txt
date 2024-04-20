.. _api-aidl:

AIDL Utilities
==============

.. automodule:: bshark.aidl

Public API
----------

.. autoattribute:: bshark.aidl.AIDL

    Public tree-sitter language object for AIDL source code
    files.

.. autoattribute:: bshark.aidl.JAVA

    Public tree-sitter language object for Java source code
    files, which was generated using `Tree-Sitter-Java <https://github.com/serenadeai/java-tree-sitter>`_

.. autofunction:: bshark.aidl.parse_aidl

.. autofunction:: bshark.aidl.parse_java

.. autoclass:: bshark.aidl.Type()
    :members:
    :undoc-members:

.. autoclass:: bshark.aidl.Unit
    :members:

Internal API
------------

.. autofunction:: bshark.aidl.get_imports

.. autofunction:: bshark.aidl.get_package

.. autofunction:: bshark.aidl.get_class_by_name

.. autofunction:: bshark.aidl.get_method_by_name

.. autofunction:: bshark.aidl.get_parcelables

.. autofunction:: bshark.aidl.get_binder_methods

.. autofunction:: bshark.aidl.get_parameters

.. autofunction:: bshark.aidl.get_methods

.. autofunction:: bshark.aidl.get_method_return_type

.. autofunction:: bshark.aidl.get_parameter_modifier
