from platform import system
from setuptools import Extension, setup

setup(
    name="bshark",
    packages=["bshark"],
    package_data={
        "bshark": ["*.pyi", "py.typed", "*.js"],
    },
    ext_modules=[
        Extension(
            name="bshark._aidl",
            sources=[
                "bshark/_aidl.c",
                "src/aidl_parser.c",
            ],
            extra_compile_args=(
                ["-std=c11"] if system() != 'Windows' else []
            ),
            define_macros=[
                # ("Py_LIMITED_API", "0x03080000"),
                ("PY_SSIZE_T_CLEAN", None)
            ],
            include_dirs=["include"],
            py_limited_api=True,
        ),
        Extension(
            name="bshark._java",
            sources=[
                "bshark/_java.c",
                "src/java_parser.c",
            ],
            extra_compile_args=(
                ["-std=c11"] if system() != 'Windows' else []
            ),
            define_macros=[
                # ("Py_LIMITED_API", "0x03080000"),
                ("PY_SSIZE_T_CLEAN", None)
            ],
            include_dirs=["include"],
            py_limited_api=True,
        )
    ],
    zip_safe=False
)
