#include <Python.h>

typedef struct TSLanguage TSLanguage;

TSLanguage *tree_sitter_aidl(void);

static PyObject *_binding_language(PyObject *self, PyObject *args) {
  return PyLong_FromVoidPtr(tree_sitter_aidl());
}

static PyMethodDef methods[] = {{"language", _binding_language, METH_NOARGS,
                                 "Returns the language reference for AIDL."},
                                {NULL, NULL, 0, NULL}};

static struct PyModuleDef module = {.m_base = PyModuleDef_HEAD_INIT,
                                    .m_name = "_aidl",
                                    .m_doc = NULL,
                                    .m_size = -1,
                                    .m_methods = methods};

PyMODINIT_FUNC PyInit__aidl(void) { return PyModule_Create(&module); }
