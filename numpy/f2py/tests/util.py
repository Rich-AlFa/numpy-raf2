"""
Utility functions for

- building and importing modules on test time, using a temporary location
- detecting if compilers are present
- determining paths to tests

"""
import glob
import os
import sys
import subprocess
import tempfile
import shutil
import atexit
import textwrap
import re
import pytest
import contextlib
import numpy
import concurrent.futures
from dataclasses import dataclass, field

from pathlib import Path
from numpy._utils import asunicode
from numpy.testing import temppath, IS_WASM
from importlib import import_module
from numpy.f2py._backends._meson import MesonBackend

#
# Maintaining a temporary module directory
#

_module_dir = None
_module_num = 5403

if sys.platform == "cygwin":
    NUMPY_INSTALL_ROOT = Path(__file__).parent.parent.parent
    _module_list = list(NUMPY_INSTALL_ROOT.glob("**/*.dll"))


def _cleanup():
    global _module_dir
    if _module_dir is not None:
        try:
            sys.path.remove(_module_dir)
        except ValueError:
            pass
        try:
            shutil.rmtree(_module_dir)
        except OSError:
            pass
        _module_dir = None


def get_module_dir():
    global _module_dir
    if _module_dir is None:
        _module_dir = tempfile.mkdtemp()
        atexit.register(_cleanup)
        if _module_dir not in sys.path:
            sys.path.insert(0, _module_dir)
    return _module_dir


def get_temp_module_name():
    # Assume single-threaded, and the module dir usable only by this thread
    global _module_num
    get_module_dir()
    name = "_test_ext_module_%d" % _module_num
    _module_num += 1
    if name in sys.modules:
        # this should not be possible, but check anyway
        raise RuntimeError("Temporary module name already in use.")
    return name


#
# Building modules
#


def build_module(source_files, options=[], skip=[], only=[], module_name=None):
    """
    Compile and import a f2py module, built from the given files.

    """

    code = f"import sys; sys.path = {sys.path!r}; import numpy.f2py; numpy.f2py.main()"

    d = get_module_dir()

    # Copy files
    dst_sources = []
    f2py_sources = []
    for fn in source_files:
        if not os.path.isfile(fn):
            raise RuntimeError("%s is not a file" % fn)
        dst = os.path.join(d, os.path.basename(fn))
        shutil.copyfile(fn, dst)
        dst_sources.append(dst)

        base, ext = os.path.splitext(dst)
        if ext in (".f90", ".f", ".c", ".pyf"):
            f2py_sources.append(dst)

    assert f2py_sources

    # Prepare options
    if module_name is None:
        module_name = get_temp_module_name()
    f2py_opts = ["-c", "-m", module_name] + options + f2py_sources
    f2py_opts += ["--backend", "meson"]
    if skip:
        f2py_opts += ["skip:"] + skip
    if only:
        f2py_opts += ["only:"] + only

    # Build
    cwd = os.getcwd()
    try:
        os.chdir(d)
        cmd = [sys.executable, "-c", code] + f2py_opts
        p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        out, err = p.communicate()
        if p.returncode != 0:
            raise RuntimeError(
                "Running f2py failed: %s\n%s" % (cmd[4:], asunicode(out))
            )
    finally:
        os.chdir(cwd)

        # Partial cleanup
        for fn in dst_sources:
            os.unlink(fn)

    # Rebase (Cygwin-only)
    if sys.platform == "cygwin":
        # If someone starts deleting modules after import, this will
        # need to change to record how big each module is, rather than
        # relying on rebase being able to find that from the files.
        _module_list.extend(glob.glob(os.path.join(d, "{:s}*".format(module_name))))
        subprocess.check_call(
            ["/usr/bin/rebase", "--database", "--oblivious", "--verbose"] + _module_list
        )

    # Import
    return import_module(module_name)


# @_memoize
def build_code(
    source_code, options=[], skip=[], only=[], suffix=None, module_name=None
):
    """
    Compile and import Fortran code using f2py.

    """
    if suffix is None:
        suffix = ".f"
    with temppath(suffix=suffix) as path:
        with open(path, "w") as f:
            f.write(source_code)
        return build_module(
            [path], options=options, skip=skip, only=only, module_name=module_name
        )


#
# Check if compilers are available at all...
#


def check_language(lang, code_snippet=None):
    tmpdir = tempfile.mkdtemp()
    try:
        meson_file = os.path.join(tmpdir, "meson.build")
        with open(meson_file, "w") as f:
            f.write("project('check_compilers')\n")
            f.write(f"add_languages('{lang}')\n")
            if code_snippet:
                f.write(f"{lang}_compiler = meson.get_compiler('{lang}')\n")
                f.write(f"{lang}_code = '''{code_snippet}'''\n")
                f.write(
                    f"_have_{lang}_feature ="
                    f"{lang}_compiler.compiles({lang}_code,"
                    f" name: '{lang} feature check')\n"
                )
        runmeson = subprocess.run(
            ["meson", "setup", "btmp"],
            check=False,
            cwd=tmpdir,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        if runmeson.returncode == 0:
            return True
        else:
            return False
    finally:
        shutil.rmtree(tmpdir)
    return False


fortran77_code = """
C Example Fortran 77 code
      PROGRAM HELLO
      PRINT *, 'Hello, Fortran 77!'
      END
"""

fortran90_code = """
! Example Fortran 90 code
program hello90
  type :: greeting
    character(len=20) :: text
  end type greeting

  type(greeting) :: greet
  greet%text = 'hello, fortran 90!'
  print *, greet%text
end program hello90
"""


# Dummy class for caching relevant checks
class CompilerChecker:
    def __init__(self):
        self.compilers_checked = False
        self.has_c = False
        self.has_f77 = False
        self.has_f90 = False

    def check_compilers(self):
        if (not self.compilers_checked) and (not sys.platform == "cygwin"):
            with concurrent.futures.ThreadPoolExecutor() as executor:
                futures = [
                    executor.submit(check_language, "c"),
                    executor.submit(check_language, "fortran", fortran77_code),
                    executor.submit(check_language, "fortran", fortran90_code),
                ]

                self.has_c = futures[0].result()
                self.has_f77 = futures[1].result()
                self.has_f90 = futures[2].result()

            self.compilers_checked = True


#
# Building with meson
#


class SimplifiedMesonBackend(MesonBackend):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

    def compile(self):
        self.write_meson_build(self.build_dir)
        self.run_meson(self.build_dir)


def build_meson(source_files, module_name=None, **kwargs):
    """
    Build a module via Meson and import it.
    """
    build_dir = get_module_dir()
    if module_name is None:
        module_name = get_temp_module_name()

    # Initialize the MesonBackend
    backend = SimplifiedMesonBackend(
        modulename=module_name,
        sources=source_files,
        extra_objects=kwargs.get("extra_objects", []),
        build_dir=build_dir,
        include_dirs=kwargs.get("include_dirs", []),
        library_dirs=kwargs.get("library_dirs", []),
        libraries=kwargs.get("libraries", []),
        define_macros=kwargs.get("define_macros", []),
        undef_macros=kwargs.get("undef_macros", []),
        f2py_flags=kwargs.get("f2py_flags", []),
        sysinfo_flags=kwargs.get("sysinfo_flags", []),
        fc_flags=kwargs.get("fc_flags", []),
        flib_flags=kwargs.get("flib_flags", []),
        setup_flags=kwargs.get("setup_flags", []),
        remove_build_dir=kwargs.get("remove_build_dir", False),
        extra_dat=kwargs.get("extra_dat", {}),
    )

    # Compile the module
    # NOTE: Catch-all since without distutils it is hard to determine which
    # compiler stack is on the CI
    try:
        backend.compile()
    except:
        pytest.skip("Failed to compile module")

    # Import the compiled module
    sys.path.insert(0, f"{build_dir}/{backend.meson_build_dir}")
    return import_module(module_name)


#
# Build helpers
#


@dataclass
class F2PyModuleSpec:
    test_class_name: str
    code: str = None
    sources: list = field(default_factory=list)
    options: list = field(default_factory=list)
    skip: list = field(default_factory=list)
    only: list = field(default_factory=list)
    suffix: str = ".f"
    module_name: str = None

    def __post_init__(self):
        # Obtain the module path from the current module's __name__
        # Mimicks this:
        # cls = type(self)
        # f'_{cls.__module__.rsplit(".",1)[-1]}_{cls.__name__}_ext_module'
        if not self.module_name:
            module_part = __name__.rsplit(".", 1)[-1]
            self.module_name = f"_{module_part}_{self.test_class_name}_ext_module"


def build_module_from_spec(spec):
    codes = spec.sources if spec.sources else []
    if spec.code:
        codes.append(spec.suffix)

    # Build the module based on the spec
    if spec.code is not None:
        module = build_code(
            spec.code,
            options=spec.options,
            skip=spec.skip,
            only=spec.only,
            suffix=spec.suffix,
            module_name=spec.module_name,
        )
    elif spec.sources is not None:
        module = build_module(
            spec.sources,
            options=spec.options,
            skip=spec.skip,
            only=spec.only,
            module_name=spec.module_name,
        )
    return module


# Helper functions
#


def getpath(*a):
    # Package root
    d = Path(numpy.f2py.__file__).parent.resolve()
    return d.joinpath(*a)


@contextlib.contextmanager
def switchdir(path):
    curpath = Path.cwd()
    os.chdir(path)
    try:
        yield
    finally:
        os.chdir(curpath)
