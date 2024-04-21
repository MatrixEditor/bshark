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
import argparse
import shlex
import pathlib

from rich import print
from rich.console import Console
from rich.tree import Tree
from rich.live import Live

from bshark.aidl import Type
from bshark.compiler import BaseLoader, Preprocessor, Compiler
from bshark.compiler.model import QName, to_json
from bshark.compiler.util import get_qname


console = Console()


def info(loader: BaseLoader, qname: QName) -> None:
    """Displays information about the given type."""
    with console.status(f"Importing [b]{qname}[/]..."):
        units = loader.import_(qname)

    tree = Tree(f"Units of [bold]{qname}[/]")
    with Live(tree):
        for unit in units:
            p = Preprocessor(unit)
            node = tree.add(f"[blue]{p.qname}[/]")
            if not p.is_valid():
                node.add("[dark_orange]Not Found![/]")
                continue
            node.add(f"Methods: [bold]{len(p.methods)}[/]")
            node.add(f"Constructors: [bold]{len(p.constructors)}[/]")
            node.add(f"Members: [bold]{len(p.members)}[/]")
            node.add(f"Compiled: [bold]{p.is_compiled()}[/]")

            if p.unit.type == Type.PARCELABLE_JAVA:
                parcelable = node.add("Parcelable")
                parcelable.add(f"Creator: [bold]{p.get_creator() is not None}[/]")
                parcelable.add(
                    f"Ctor: [bold]{p.get_parcel_constructor() is not None}[/]"
                )

            info_node = node.add("Info")
            info_node.add(f"QName: [green]{p.qname!r}[/]")
            info_node.add(f"RPath: [green]{p.rpath!r}[/]")
            info_node.add(f"Lang: [green]{p.lang.name!r}[/]")


def compile_single(loader: BaseLoader, qname: QName, output: str, force: bool) -> None:
    """Compiles the given type."""
    with console.status(f"Importing [b]{qname}[/]..."):
        try:
            units = loader.import_(qname)
        except ImportError:
            console.log(f"[dark_orange]Not found:[/] {qname} - aborting")
            return

    with console.status(f"Compiling [b]{qname}[/]..."):
        for unit in units:
            c = Compiler(unit, loader)
            if not c.info.is_valid():
                console.log(f"[dark_orange]Not found:[/] {c.info.qname} - aborting")
                continue

            output_path = os.path.join(output, f"{c.info.qname}.json")
            if os.path.exists(output_path) and not force:
                console.log(f"[green]Already exists:[/] {c.info.qname} - skipping")
                continue

            if c.info.is_compiled():
                console.log(f"[green]Already compiled:[/] {c.info.qname} - skipping")
                continue

            definition = None
            try:
                match c.unit.type:
                    # Try to compile as a parcelable with a Java definition
                    case Type.PARCELABLE_JAVA:
                        definition = c.as_parcelable()

                    case Type.BINDER:
                        definition = c.as_binder()

                    case _:
                        console.log(
                            f"[dark_orange]Not supported:[/] {c.info.qname} with {c.unit.type.name} - aborting"
                        )
                        continue
            except:  # pylint: disable=bare-except
                console.log(f"[red]Failed:[/] {c.info.qname} - aborting")
                # console.print_exception(show_locals=True)
                return

            with open(output_path, "w", encoding="utf-8") as fp:
                fp.write(to_json(definition))

            console.log(
                f"[green]Compiled:[/] {c.info.qname} - {c.info.rpath} - {c.info.lang.name}"
            )


def compile_batch(
    loader: BaseLoader, output: str, force: bool, recursive: bool
) -> None:
    abs_out_dir = os.path.abspath(output)
    os.makedirs(abs_out_dir, exist_ok=True)

    files = set()
    with console.status("Collecting AIDL files..."):
        for search_root in loader.search_path:
            abs_in_dir = os.path.abspath(search_root)
            if not os.path.isdir(abs_in_dir):
                continue

            input_dir_pathobj = pathlib.Path(abs_in_dir)
            aidl_files = []
            if recursive:
                aidl_files = input_dir_pathobj.rglob("*.aidl")
            else:
                aidl_files = input_dir_pathobj.glob("*.aidl")

            files.update(
                map(lambda x: get_qname(str(x).replace(abs_in_dir, "")), aidl_files)
            )

    console.log(f"Found [{'green' if len(files) > 0 else 'red'}]{len(files)} [/]AIDL files")
    with console.status("Loading cached files..."):
        loader.import_("*")

    for file in sorted(files):
        qname = str(file).replace(abs_in_dir, "").strip("/")
        compile_single(loader, qname, abs_out_dir, force)


def main(cmd: t.Optional[str] = None):
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "-I",
        dest="includes",
        action="append",
        default=[],
        help="Directories to add to the loader's search path",
    )
    parsers = parser.add_subparsers()

    info_parser = parsers.add_parser(
        "info", help="Displays information about the given type"
    )
    info_parser.add_argument(
        "qname",
        type=str,
        help="The qualified name of the type (e.g. 'android.app.IActivityManager')",
    )
    info_parser.set_defaults(func=info)

    compilation_parser = parsers.add_parser("compile", help="Compiles the given type")
    compilation_parser.add_argument(
        "qname",
        type=str,
        help="The qualified name of the type (e.g. 'android.app.IActivityManager')",
    )
    compilation_parser.add_argument(
        "-o",
        dest="output",
        type=str,
        default=".",
        help="The output directory for the generated files",
    )
    compilation_parser.add_argument(
        "-f",
        "--force",
        dest="force",
        action="store_true",
        help="Force recompilation of the given type",
    )
    compilation_parser.set_defaults(func=compile_single)

    batch_cp_parser = parsers.add_parser(
        "batch-compile", help="Compiles all AIDL files in the given include directories"
    )
    batch_cp_parser.add_argument(
        "-o",
        dest="output",
        type=str,
        default=".",
        help="The output directory for the generated files",
    )
    batch_cp_parser.add_argument(
        "-r",
        "--recursive",
        dest="recursive",
        action="store_true",
        help="Recursively search for AIDL files in subdirectories",
    )
    batch_cp_parser.add_argument(
        "-f",
        "--force",
        dest="force",
        action="store_true",
        help="Force recompilation of the given type",
    )
    batch_cp_parser.set_defaults(func=compile_batch)

    args = parser.parse_args(shlex.split(cmd) if cmd else None).__dict__
    loader = BaseLoader(args.pop("includes"))
    args.pop("func")(loader, **args)


if __name__ == "__main__":
    main()
