.. _api-index:

################################
        Library Internals
################################

*This library is a WIP and may change in the future. Please be aware
that there may be breaking changes before the first release.*

*bshark* heavily depends on parsing AIDL and Java source code files. It
leverages the speed of `Tree-Sitter <https://tree-sitter.github.io/tree-sitter/>`_
to work with them and uses `Caterpillar <https://matrixeditor.github.io/caterpillar/>`_
to parse received transaction messages.

.. toctree::
    :maxdepth: 2
    :caption: Basic API

    aidl.rst


.. toctree::
    :maxdepth: 2
    :caption: Compiler API

    compilermodel.rst
    loader.rst
    compiler.rst
    compilerutilities.rst
