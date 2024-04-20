#include <Python.h>

typedef struct TSLanguage TSLanguage;

TSLanguage *tree_sitter_java(void);

static PyObject *_binding_language(PyObject *self, PyObject *args) {
  return PyLong_FromVoidPtr(tree_sitter_java());
}

static PyMethodDef methods[] = {
    {"language",                                  /* ml_name */
     _binding_language,                           /* ml_meth */
     METH_NOARGS,                                 /* ml_flags */
     "Returns the language reference for Java."}, /* ml_doc */
    {NULL, NULL, 0, NULL}};

static struct PyModuleDef module = {.m_base = PyModuleDef_HEAD_INIT,
                                    .m_name = "_java",
                                    .m_doc = NULL,
                                    .m_size = -1,
                                    .m_methods = methods};

PyMODINIT_FUNC PyInit__java(void) { return PyModule_Create(&module); }
