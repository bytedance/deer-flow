# Generated automatically from Makefile.pre by makesetup.
# Top-level Makefile for Python
#
# As distributed, this file is called Makefile.pre.in; it is processed
# into the real Makefile by running the script ./configure, which
# replaces things like @spam@ with values appropriate for your system.
# This means that if you edit Makefile, your changes get lost the next
# time you run the configure script.  Ideally, you can do:
#
#	./configure
#	make
#	make test
#	make install
#
# If you have a previous version of Python installed that you don't
# want to overwrite, you can use "make altinstall" instead of "make
# install".  Refer to the "Installing" section in the README file for
# additional details.
#
# See also the section "Build instructions" in the README file.

# === Variables set by makesetup ===

MODBUILT_NAMES=      posix  errno  pwd  _sre  _codecs  _weakref  _functools  _operator  _collections  _abc  itertools  atexit  _signal  _stat  time  _thread  _locale  _io  faulthandler  _tracemalloc  _symtable  xxsubtype
MODDISABLED_NAMES= 
MODOBJS=             Modules/posixmodule.o  Modules/errnomodule.o  Modules/pwdmodule.o  Modules/_sre.o  Modules/_codecsmodule.o  Modules/_weakref.o  Modules/_functoolsmodule.o  Modules/_operator.o  Modules/_collectionsmodule.o  Modules/_abc.o  Modules/itertoolsmodule.o  Modules/atexitmodule.o  Modules/signalmodule.o  Modules/_stat.o  Modules/timemodule.o  Modules/_threadmodule.o  Modules/_localemodule.o  Modules/_iomodule.o Modules/iobase.o Modules/fileio.o Modules/bytesio.o Modules/bufferedio.o Modules/textio.o Modules/stringio.o  Modules/faulthandler.o  Modules/_tracemalloc.o  Modules/symtablemodule.o  Modules/xxsubtype.o
MODLIBS=           $(LOCALMODLIBS) $(BASEMODLIBS)

# === Variables set by configure
VERSION=	3.10
srcdir=		/croot/python-split_1749128751284/work
VPATH=		/croot/python-split_1749128751284/work
abs_srcdir=	/croot/python-split_1749128751284/work
abs_builddir=	/croot/python-split_1749128751284/work/build-static


CC=		x86_64-conda-linux-gnu-gcc -pthread
CXX=		x86_64-conda-linux-gnu-c++ -pthread
MAINCC=		$(CC)
LINKCC=		$(PURIFY) $(MAINCC)
AR=		x86_64-conda-linux-gnu-ar
READELF=	x86_64-conda-linux-gnu-readelf
SOABI=		cpython-310-x86_64-linux-gnu
LDVERSION=	$(VERSION)$(ABIFLAGS)
LIBPYTHON=	
GITVERSION=	
GITTAG=		
GITBRANCH=	
PGO_PROF_GEN_FLAG=-fprofile-generate
PGO_PROF_USE_FLAG= 
LLVM_PROF_MERGER=true
LLVM_PROF_FILE=
LLVM_PROF_ERR=no
DTRACE=         
DFLAGS=         
DTRACE_HEADERS= 
DTRACE_OBJS=    

GNULD=		yes

# Shell used by make (some versions default to the login shell, which is bad)
SHELL=		/bin/sh

# Use this to make a link between python$(VERSION) and python in $(BINDIR)
LN=		ln

# Portable install script (configure doesn't always guess right)
INSTALL=	/usr/bin/install -c
INSTALL_PROGRAM=${INSTALL}
INSTALL_SCRIPT= ${INSTALL}
INSTALL_DATA=	${INSTALL} -m 644
# Shared libraries must be installed with executable mode on some systems;
# rather than figuring out exactly which, we always give them executable mode.
INSTALL_SHARED= ${INSTALL} -m 755

MKDIR_P=	/usr/bin/mkdir -p

MAKESETUP=      $(srcdir)/Modules/makesetup

# Compiler options
OPT=		-DNDEBUG -fwrapv -O2 -Wall
BASECFLAGS=	 -Wno-unused-result -Wsign-compare
BASECPPFLAGS=	-IObjects -IInclude -IPython
CONFIGURE_CFLAGS=	-march=nocona -mtune=haswell -ftree-vectorize -fPIC -fstack-protector-strong -fno-plt -O2 -ffunction-sections -pipe -isystem /home/kie/code/deer-flow/.conda/include -fdebug-prefix-map=/croot/python-split_1749128751284/work=/usr/local/src/conda/python-3.10.18 -fdebug-prefix-map=/home/kie/code/deer-flow/.conda=/usr/local/src/conda-prefix    
# CFLAGS_NODIST is used for building the interpreter and stdlib C extensions.
# Use it when a compiler flag should _not_ be part of the distutils CFLAGS
# once Python is installed (Issue #21121).
CONFIGURE_CFLAGS_NODIST= -fno-semantic-interposition     -g -std=c99 -Wextra -Wno-unused-result -Wno-unused-parameter -Wno-missing-field-initializers -Werror=implicit-function-declaration -fvisibility=hidden
# LDFLAGS_NODIST is used in the same manner as CFLAGS_NODIST.
# Use it when a linker flag should _not_ be part of the distutils LDFLAGS
# once Python is installed (bpo-35257)
CONFIGURE_LDFLAGS_NODIST= -fno-semantic-interposition     -g
CONFIGURE_CPPFLAGS=	-DNDEBUG -D_FORTIFY_SOURCE=2 -O2 -isystem /home/kie/code/deer-flow/.conda/include -I/home/kie/code/deer-flow/.conda/include
CONFIGURE_LDFLAGS=	-Wl,-O2 -Wl,--sort-common -Wl,--as-needed -Wl,-z,relro -Wl,-z,now -Wl,--disable-new-dtags -Wl,--gc-sections -Wl,-rpath,/home/kie/code/deer-flow/.conda/lib -Wl,-rpath-link,/home/kie/code/deer-flow/.conda/lib -L/home/kie/code/deer-flow/.conda/lib
# Avoid assigning CFLAGS, LDFLAGS, etc. so users can use them on the
# command line to append to these values without stomping the pre-set
# values.
PY_CFLAGS=	$(BASECFLAGS) $(OPT) $(CONFIGURE_CFLAGS) $(CFLAGS) $(EXTRA_CFLAGS)
PY_CFLAGS_NODIST=$(CONFIGURE_CFLAGS_NODIST) $(CFLAGS_NODIST) -I$(srcdir)/Include/internal
# Both CPPFLAGS and LDFLAGS need to contain the shell's value for setup.py to
# be able to build extension modules using the directories specified in the
# environment variables
PY_CPPFLAGS=	$(BASECPPFLAGS) -I. -I$(srcdir)/Include $(CONFIGURE_CPPFLAGS) $(CPPFLAGS)
PY_LDFLAGS=	$(CONFIGURE_LDFLAGS) $(LDFLAGS)
PY_LDFLAGS_NODIST=$(CONFIGURE_LDFLAGS_NODIST) $(LDFLAGS_NODIST)
NO_AS_NEEDED=	-Wl,--no-as-needed
CCSHARED=	-fPIC
# LINKFORSHARED are the flags passed to the $(CC) command that links
# the python executable -- this is only needed for a few systems
LINKFORSHARED=	-Xlinker -export-dynamic
ARFLAGS=	rcs
# Extra C flags added for building the interpreter object files.
CFLAGSFORSHARED=
# C flags used for building the interpreter object files
PY_STDMODULE_CFLAGS= $(PY_CFLAGS) $(PY_CFLAGS_NODIST) $(PY_CPPFLAGS) $(CFLAGSFORSHARED)
PY_BUILTIN_MODULE_CFLAGS= $(PY_STDMODULE_CFLAGS) -DPy_BUILD_CORE_BUILTIN
PY_CORE_CFLAGS=	$(PY_STDMODULE_CFLAGS) -DPy_BUILD_CORE
# Linker flags used for building the interpreter object files
PY_CORE_LDFLAGS=$(PY_LDFLAGS) $(PY_LDFLAGS_NODIST)
# Strict or non-strict aliasing flags used to compile dtoa.c, see above
CFLAGS_ALIASING=


# Machine-dependent subdirectories
MACHDEP=	linux

# Multiarch directory (may be empty)
MULTIARCH=	x86_64-linux-gnu
MULTIARCH_CPPFLAGS = -DMULTIARCH=\"x86_64-linux-gnu\"

# Install prefix for architecture-independent files
prefix=		/home/kie/code/deer-flow/.conda

# Install prefix for architecture-dependent files
exec_prefix=	${prefix}

# Install prefix for data files
datarootdir=    ${prefix}/share

# Expanded directories
BINDIR=		${exec_prefix}/bin
LIBDIR=		${exec_prefix}/lib
MANDIR=		${datarootdir}/man
INCLUDEDIR=	${prefix}/include
CONFINCLUDEDIR=	$(exec_prefix)/include
PLATLIBDIR=	lib
SCRIPTDIR=	$(prefix)/$(PLATLIBDIR)
ABIFLAGS=	
# Variable used by ensurepip
WHEEL_PKG_DIR=	

# Detailed destination directories
BINLIBDEST=	${exec_prefix}/${PLATLIBDIR}/python$(VERSION)
LIBDEST=	$(SCRIPTDIR)/python$(VERSION)
INCLUDEPY=	$(INCLUDEDIR)/python$(LDVERSION)
CONFINCLUDEPY=	$(CONFINCLUDEDIR)/python$(LDVERSION)

# Symbols used for using shared libraries
SHLIB_SUFFIX=	.so
EXT_SUFFIX=	.cpython-310-x86_64-linux-gnu.so
LDSHARED=	$(CC) -shared $(PY_LDFLAGS)
BLDSHARED=	$(CC) -shared $(PY_CORE_LDFLAGS)
LDCXXSHARED=	$(CXX) -shared
DESTSHARED=	$(BINLIBDEST)/lib-dynload

# List of exported symbols for AIX
EXPORTSYMS=	
EXPORTSFROM=	

# Executable suffix (.exe on Windows and Mac OS X)
EXE=		
BUILDEXE=	

# Short name and location for Mac OS X Python framework
UNIVERSALSDK=
PYTHONFRAMEWORK=	
PYTHONFRAMEWORKDIR=	no-framework
PYTHONFRAMEWORKPREFIX=	
PYTHONFRAMEWORKINSTALLDIR= 
# Deployment target selected during configure, to be checked
# by distutils. The export statement is needed to ensure that the
# deployment target is active during build.
MACOSX_DEPLOYMENT_TARGET=
#export MACOSX_DEPLOYMENT_TARGET

# Option to install to strip binaries
STRIPFLAG=-s

# Flags to lipo to produce a 32-bit-only universal executable
LIPO_32BIT_FLAGS=

# Flags to lipo to produce an intel-64-only universal executable
LIPO_INTEL64_FLAGS=

# Options to enable prebinding (for fast startup prior to Mac OS X 10.3)
OTHER_LIBTOOL_OPT=

# Environment to run shared python without installed libraries
RUNSHARED=       

# ensurepip options
ENSUREPIP=      no

# OpenSSL options for setup.py so sysconfig can pick up AC_SUBST() vars.
OPENSSL_INCLUDES=-I/home/kie/code/deer-flow/.conda/include
OPENSSL_LIBS=-lssl -lcrypto
OPENSSL_LDFLAGS=-L/home/kie/code/deer-flow/.conda/lib
OPENSSL_RPATH=

# Default zoneinfo.TZPATH. Added here to expose it in sysconfig.get_config_var
TZPATH=/home/kie/code/deer-flow/.conda/share/zoneinfo

# Modes for directories, executables and data files created by the
# install process.  Default to user-only-writable for all file types.
DIRMODE=	755
EXEMODE=	755
FILEMODE=	644

# configure script arguments
CONFIG_ARGS=	 '--prefix=/home/kie/code/deer-flow/.conda' '--build=x86_64-conda-linux-gnu' '--host=x86_64-conda-linux-gnu' '--enable-ipv6' '--with-ensurepip=no' '--with-tzpath=/home/kie/code/deer-flow/.conda/share/zoneinfo' '--with-computed-gotos' '--with-system-ffi' '--with-system-expat' '--enable-loadable-sqlite-extensions' '--with-tcltk-includes=-I/home/kie/code/deer-flow/.conda/include' '--with-tcltk-libs=-L/home/kie/code/deer-flow/.conda/lib -ltcl8.6 -ltk8.6' '--with-platlibdir=lib' '--with-lto' '--enable-optimizations' '-oldincludedir=/croot/python-split_1749128751284/_build_env/x86_64-conda-linux-gnu/sysroot/usr/include' '--disable-shared' 'PROFILE_TASK=-m test --pgo' 'build_alias=x86_64-conda-linux-gnu' 'host_alias=x86_64-conda-linux-gnu' 'MACHDEP=linux' 'CC=x86_64-conda-linux-gnu-gcc' 'CFLAGS=-march=nocona -mtune=haswell -ftree-vectorize -fPIC -fstack-protector-strong -fno-plt -O2 -ffunction-sections -pipe -isystem /home/kie/code/deer-flow/.conda/include -fdebug-prefix-map=/croot/python-split_1749128751284/work=/usr/local/src/conda/python-3.10.18 -fdebug-prefix-map=/home/kie/code/deer-flow/.conda=/usr/local/src/conda-prefix    ' 'LDFLAGS=-Wl,-O2 -Wl,--sort-common -Wl,--as-needed -Wl,-z,relro -Wl,-z,now -Wl,--disable-new-dtags -Wl,--gc-sections -Wl,-rpath,/home/kie/code/deer-flow/.conda/lib -Wl,-rpath-link,/home/kie/code/deer-flow/.conda/lib -L/home/kie/code/deer-flow/.conda/lib' 'CPPFLAGS=-DNDEBUG -D_FORTIFY_SOURCE=2 -O2 -isystem /home/kie/code/deer-flow/.conda/include -I/home/kie/code/deer-flow/.conda/include' 'CPP=/croot/python-split_1749128751284/_build_env/bin/x86_64-conda-linux-gnu-cpp' 'PKG_CONFIG_PATH=/home/kie/code/deer-flow/.conda/lib/pkgconfig'


# Subdirectories with code
SRCDIRS= 	Parser Objects Python Modules Modules/_io Programs

# Other subdirectories
SUBDIRSTOO=	Include Lib Misc

# Files and directories to be distributed
CONFIGFILES=	configure configure.ac acconfig.h pyconfig.h.in Makefile.pre.in
DISTFILES=	README.rst ChangeLog $(CONFIGFILES)
DISTDIRS=	$(SUBDIRS) $(SUBDIRSTOO) Ext-dummy
DIST=		$(DISTFILES) $(DISTDIRS)


LIBRARY=	libpython$(VERSION)$(ABIFLAGS).a
LDLIBRARY=      libpython$(VERSION)$(ABIFLAGS).a
BLDLIBRARY=     $(LDLIBRARY)
PY3LIBRARY=     
DLLLIBRARY=	
LDLIBRARYDIR=   
INSTSONAME=	$(LDLIBRARY)
LIBRARY_DEPS=	$(LIBRARY) $(PY3LIBRARY) $(EXPORTSYMS)
PY_ENABLE_SHARED=	0
STATIC_LIBPYTHON=	1


LIBS=		-lcrypt -lpthread -ldl  -lutil -lm
LIBM=		-lm
LIBC=		
SYSLIBS=	$(LIBM) $(LIBC)
SHLIBS=		$(LIBS)

DLINCLDIR=	.
DYNLOADFILE=	dynload_shlib.o
MACHDEP_OBJS=	
LIBOBJDIR=	Python/
LIBOBJS=	

PYTHON=		python$(EXE)
BUILDPYTHON=	python$(BUILDEXE)

PYTHON_FOR_REGEN?=python3
UPDATE_FILE=$(PYTHON_FOR_REGEN) $(srcdir)/Tools/scripts/update_file.py
PY_BUILD_ENVIRON=
PYTHON_FOR_BUILD=./$(BUILDPYTHON) -E
_PYTHON_HOST_PLATFORM=linux-x86_64
BUILD_GNU_TYPE=	x86_64-conda-linux-gnu
HOST_GNU_TYPE=	x86_64-conda-linux-gnu

# Tcl and Tk config info from --with-tcltk-includes and -libs options
TCLTK_INCLUDES=	-I/home/kie/code/deer-flow/.conda/include
TCLTK_LIBS=	-L/home/kie/code/deer-flow/.conda/lib -ltcl8.6 -ltk8.6

# The task to run while instrumented when building the profile-opt target.
# To speed up profile generation, we don't run the full unit test suite
# by default. The default is "-m test --pgo". To run more tests, use
# PROFILE_TASK="-m test --pgo-extended"
PROFILE_TASK=	-m test --pgo

# report files for gcov / lcov coverage report
COVERAGE_INFO=	$(abs_builddir)/coverage.info
COVERAGE_REPORT=$(abs_builddir)/lcov-report
COVERAGE_REPORT_OPTIONS=--no-branch-coverage --title "CPython lcov report"


# === Definitions added by makesetup ===

LOCALMODLIBS=                      
BASEMODLIBS=
PYTHONPATH=$(COREPYTHONPATH)
COREPYTHONPATH=$(DESTPATH)$(SITEPATH)$(TESTPATH)
TESTPATH=
SITEPATH=
DESTPATH=
MACHDESTLIB=$(BINLIBDEST)
DESTLIB=$(LIBDEST)



##########################################################################
# Modules
MODULE_OBJS=	\
		Modules/config.o \
		Modules/getpath.o \
		Modules/main.o \
		Modules/gcmodule.o

IO_H=		Modules/_io/_iomodule.h

IO_OBJS=	\
		Modules/_io/_iomodule.o \
		Modules/_io/iobase.o \
		Modules/_io/fileio.o \
		Modules/_io/bufferedio.o \
		Modules/_io/textio.o \
		Modules/_io/bytesio.o \
		Modules/_io/stringio.o

##########################################################################

LIBFFI_INCLUDEDIR=	/home/kie/code/deer-flow/.conda/include

##########################################################################
# Parser

PEGEN_OBJS=		\
		Parser/pegen.o \
		Parser/parser.o \
		Parser/string_parser.o \
		Parser/peg_api.o


PEGEN_HEADERS= \
		$(srcdir)/Include/internal/pycore_parser.h \
		$(srcdir)/Parser/pegen.h \
		$(srcdir)/Parser/string_parser.h

POBJS=		\
		Parser/token.o \

PARSER_OBJS=	$(POBJS) $(PEGEN_OBJS) Parser/myreadline.o Parser/tokenizer.o

PARSER_HEADERS= \
		$(PEGEN_HEADERS) \
		$(srcdir)/Parser/tokenizer.h

##########################################################################
# Python

PYTHON_OBJS=	\
		Python/_warnings.o \
		Python/Python-ast.o \
		Python/asdl.o \
		Python/ast.o \
		Python/ast_opt.o \
		Python/ast_unparse.o \
		Python/bltinmodule.o \
		Python/ceval.o \
		Python/codecs.o \
		Python/compile.o \
		Python/context.o \
		Python/dynamic_annotations.o \
		Python/errors.o \
		Python/frozenmain.o \
		Python/future.o \
		Python/getargs.o \
		Python/getcompiler.o \
		Python/getcopyright.o \
		Python/getplatform.o \
		Python/getversion.o \
		Python/hamt.o \
		Python/hashtable.o \
		Python/import.o \
		Python/importdl.o \
		Python/initconfig.o \
		Python/marshal.o \
		Python/modsupport.o \
		Python/mysnprintf.o \
		Python/mystrtoul.o \
		Python/pathconfig.o \
		Python/preconfig.o \
		Python/pyarena.o \
		Python/pyctype.o \
		Python/pyfpe.o \
		Python/pyhash.o \
		Python/pylifecycle.o \
		Python/pymath.o \
		Python/pystate.o \
		Python/pythonrun.o \
		Python/pytime.o \
		Python/bootstrap_hash.o \
		Python/structmember.o \
		Python/symtable.o \
		Python/sysmodule.o \
		Python/thread.o \
		Python/traceback.o \
		Python/getopt.o \
		Python/pystrcmp.o \
		Python/pystrtod.o \
		Python/pystrhex.o \
		Python/dtoa.o \
		Python/formatter_unicode.o \
		Python/fileutils.o \
		Python/suggestions.o \
		Python/$(DYNLOADFILE) \
		$(LIBOBJS) \
		$(MACHDEP_OBJS) \
		$(DTRACE_OBJS)


##########################################################################
# Objects
OBJECT_OBJS=	\
		Objects/abstract.o \
		Objects/accu.o \
		Objects/boolobject.o \
		Objects/bytes_methods.o \
		Objects/bytearrayobject.o \
		Objects/bytesobject.o \
		Objects/call.o \
		Objects/capsule.o \
		Objects/cellobject.o \
		Objects/classobject.o \
		Objects/codeobject.o \
		Objects/complexobject.o \
		Objects/descrobject.o \
		Objects/enumobject.o \
		Objects/exceptions.o \
		Objects/genericaliasobject.o \
		Objects/genobject.o \
		Objects/fileobject.o \
		Objects/floatobject.o \
		Objects/frameobject.o \
		Objects/funcobject.o \
		Objects/interpreteridobject.o \
		Objects/iterobject.o \
		Objects/listobject.o \
		Objects/longobject.o \
		Objects/dictobject.o \
		Objects/odictobject.o \
		Objects/memoryobject.o \
		Objects/methodobject.o \
		Objects/moduleobject.o \
		Objects/namespaceobject.o \
		Objects/object.o \
		Objects/obmalloc.o \
		Objects/picklebufobject.o \
		Objects/rangeobject.o \
		Objects/setobject.o \
		Objects/sliceobject.o \
		Objects/structseq.o \
		Objects/tupleobject.o \
		Objects/typeobject.o \
		Objects/unicodeobject.o \
		Objects/unicodectype.o \
		Objects/unionobject.o \
		Objects/weakrefobject.o

##########################################################################
# objects that get linked into the Python library
LIBRARY_OBJS_OMIT_FROZEN=	\
		Modules/getbuildinfo.o \
		$(PARSER_OBJS) \
		$(OBJECT_OBJS) \
		$(PYTHON_OBJS) \
		$(MODULE_OBJS) \
		$(MODOBJS)

LIBRARY_OBJS=	\
		$(LIBRARY_OBJS_OMIT_FROZEN) \
		Python/frozen.o

##########################################################################
# DTrace

# On some systems, object files that reference DTrace probes need to be modified
# in-place by dtrace(1).
DTRACE_DEPS = \
	Python/ceval.o Python/import.o Python/sysmodule.o Modules/gcmodule.o

#########################################################################
# Rules

# Default target
all:		profile-opt
build_all:	check-clean-src $(BUILDPYTHON) oldsharedmods sharedmods gdbhooks \
		Programs/_testembed python-config

# Check that the source is clean when building out of source.
check-clean-src:
	@if test -n "$(VPATH)" -a -f "$(srcdir)/Programs/python.o"; then \
		echo "Error: The source directory ($(srcdir)) is not clean" ; \
		echo "Building Python out of the source tree (in $(abs_builddir)) requires a clean source tree ($(abs_srcdir))" ; \
		echo "Try to run: make -C \"$(srcdir)\" clean" ; \
		exit 1; \
	fi

# Profile generation build must start from a clean tree.
profile-clean-stamp:
	$(MAKE) clean
	touch $@

# Compile with profile generation enabled.
profile-gen-stamp: profile-clean-stamp
	@if [ $(LLVM_PROF_ERR) = yes ]; then \
		echo "Error: Cannot perform PGO build because llvm-profdata was not found in PATH" ;\
		echo "Please add it to PATH and run ./configure again" ;\
		exit 1;\
	fi
	@echo "Building with support for profile generation:"
	$(MAKE) build_all_generate_profile
	touch $@

# Run task with profile generation build to create profile information.
profile-run-stamp:
	@echo "Running code to generate profile data (this can take a while):"
	# First, we need to create a clean build with profile generation
	# enabled.
	$(MAKE) profile-gen-stamp
	# Next, run the profile task to generate the profile information.
	$(MAKE) run_profile_task
	$(MAKE) build_all_merge_profile
	# Remove profile generation binary since we are done with it.
	$(MAKE) clean-retain-profile
	# This is an expensive target to build and it does not have proper
	# makefile dependency information.  So, we create a "stamp" file
	# to record its completion and avoid re-running it.
	touch $@

build_all_generate_profile:
	$(MAKE) build_all CFLAGS_NODIST="$(CFLAGS_NODIST) $(PGO_PROF_GEN_FLAG)" LDFLAGS_NODIST="$(LDFLAGS_NODIST) $(PGO_PROF_GEN_FLAG)" LIBS="$(LIBS)"

run_profile_task:
	@ # FIXME: can't run for a cross build
	$(LLVM_PROF_FILE) $(RUNSHARED) ./$(BUILDPYTHON) $(PROFILE_TASK) || true

build_all_merge_profile:
	$(LLVM_PROF_MERGER)

# Compile Python binary with profile guided optimization.
# To force re-running of the profile task, remove the profile-run-stamp file.
profile-opt: profile-run-stamp
	@echo "Rebuilding with profile guided optimizations:"
	-rm -f profile-clean-stamp
	$(MAKE) build_all CFLAGS_NODIST="$(CFLAGS_NODIST) $(PGO_PROF_USE_FLAG)" LDFLAGS_NODIST="$(LDFLAGS_NODIST)"

# Compile and run with gcov
.PHONY=coverage coverage-lcov coverage-report
coverage:
	@echo "Building with support for coverage checking:"
	$(MAKE) clean
	$(MAKE) build_all CFLAGS="$(CFLAGS) -O0 -pg --coverage" LIBS="$(LIBS) --coverage"

coverage-lcov:
	@echo "Creating Coverage HTML report with LCOV:"
	@rm -f $(COVERAGE_INFO)
	@rm -rf $(COVERAGE_REPORT)
	@lcov --capture --directory $(abs_builddir) \
	    --base-directory $(realpath $(abs_builddir)) \
	    --path $(realpath $(abs_srcdir)) \
	    --output-file $(COVERAGE_INFO)
	@ # remove 3rd party modules, system headers and internal files with
	@ # debug, test or dummy functions.
	@lcov --remove $(COVERAGE_INFO) \
	    '*/Modules/_blake2/impl/*' \
	    '*/Modules/_ctypes/libffi*/*' \
	    '*/Modules/_decimal/libmpdec/*' \
	    '*/Modules/_sha3/kcp/*' \
	    '*/Modules/expat/*' \
	    '*/Modules/zlib/*' \
	    '*/Include/*' \
	    '*/Modules/xx*.c' \
	    '*/Python/pyfpe.c' \
	    '*/Python/pystrcmp.c' \
	    '/usr/include/*' \
	    '/usr/local/include/*' \
	    '/usr/lib/gcc/*' \
	    --output-file $(COVERAGE_INFO)
	@genhtml $(COVERAGE_INFO) --output-directory $(COVERAGE_REPORT) \
	    $(COVERAGE_REPORT_OPTIONS)
	@echo
	@echo "lcov report at $(COVERAGE_REPORT)/index.html"
	@echo

# Force regeneration of parser and importlib
coverage-report: regen-token regen-importlib
	@ # build with coverage info
	$(MAKE) coverage
	@ # run tests, ignore failures
	$(TESTRUNNER) $(TESTOPTS) || true
	@ # build lcov report
	$(MAKE) coverage-lcov

# Run "Argument Clinic" over all source files
.PHONY=clinic
clinic: check-clean-src $(srcdir)/Modules/_blake2/blake2s_impl.c
	$(PYTHON_FOR_REGEN) $(srcdir)/Tools/clinic/clinic.py --make --srcdir $(srcdir)

# Build the interpreter
$(BUILDPYTHON):	Programs/python.o $(LIBRARY_DEPS)
	$(LINKCC) $(PY_CORE_LDFLAGS) $(LINKFORSHARED) -o $@ Programs/python.o $(BLDLIBRARY) $(LIBS) $(MODLIBS) $(SYSLIBS)

platform: $(BUILDPYTHON) pybuilddir.txt
	$(RUNSHARED) $(PY_BUILD_ENVIRON) $(PYTHON_FOR_BUILD) -c 'import sys ; from sysconfig import get_platform ; print("%s-%d.%d" % (get_platform(), *sys.version_info[:2]))' >platform

# Create build directory and generate the sysconfig build-time data there.
# pybuilddir.txt contains the name of the build dir and is used for
# sys.path fixup -- see Modules/getpath.c.
# Since this step runs before shared modules are built, try to avoid bootstrap
# problems by creating a dummy pybuilddir.txt just to allow interpreter
# initialization to succeed.  It will be overwritten by generate-posix-vars
# or removed in case of failure.
pybuilddir.txt: $(BUILDPYTHON)
	@echo "none" > ./pybuilddir.txt
	$(RUNSHARED) $(PY_BUILD_ENVIRON) $(PYTHON_FOR_BUILD) -S -m sysconfig --generate-posix-vars ;\
	if test $$? -ne 0 ; then \
		echo "generate-posix-vars failed" ; \
		rm -f ./pybuilddir.txt ; \
		exit 1 ; \
	fi

# This is shared by the math and cmath modules
Modules/_math.o: Modules/_math.c Modules/_math.h
	$(CC) -c $(CCSHARED) $(PY_CORE_CFLAGS) -o $@ $<

# blake2s is auto-generated from blake2b
$(srcdir)/Modules/_blake2/blake2s_impl.c: $(srcdir)/Modules/_blake2/blake2b_impl.c $(srcdir)/Modules/_blake2/blake2b2s.py
	$(PYTHON_FOR_REGEN) $(srcdir)/Modules/_blake2/blake2b2s.py
	$(PYTHON_FOR_REGEN) $(srcdir)/Tools/clinic/clinic.py -f $@

# Build the shared modules
# Under GNU make, MAKEFLAGS are sorted and normalized; the 's' for
# -s, --silent or --quiet is always the first char.
# Under BSD make, MAKEFLAGS might be " -s -v x=y".
# Ignore macros passed by GNU make, passed after --
sharedmods: $(BUILDPYTHON) pybuilddir.txt Modules/_math.o
	@case "`echo X $$MAKEFLAGS | sed 's/^X //;s/ -- .*//'`" in \
	    *\ -s*|s*) quiet="-q";; \
	    *) quiet="";; \
	esac; \
	echo "$(RUNSHARED) CC='$(CC)' LDSHARED='$(BLDSHARED)' OPT='$(OPT)' \
		_TCLTK_INCLUDES='$(TCLTK_INCLUDES)' _TCLTK_LIBS='$(TCLTK_LIBS)' \
		$(PYTHON_FOR_BUILD) $(srcdir)/setup.py $$quiet build"; \
	$(RUNSHARED) CC='$(CC)' LDSHARED='$(BLDSHARED)' OPT='$(OPT)' \
		_TCLTK_INCLUDES='$(TCLTK_INCLUDES)' _TCLTK_LIBS='$(TCLTK_LIBS)' \
		$(PY_BUILD_ENVIRON) $(PYTHON_FOR_BUILD) $(srcdir)/setup.py $$quiet build


# Build static library
$(LIBRARY): $(LIBRARY_OBJS)
	-rm -f $@
	$(AR) $(ARFLAGS) $@ $(LIBRARY_OBJS)

libpython$(LDVERSION).so: $(LIBRARY_OBJS) $(DTRACE_OBJS)
	if test $(INSTSONAME) != $(LDLIBRARY); then \
		$(BLDSHARED) -Wl,-h$(INSTSONAME) -o $(INSTSONAME) $(LIBRARY_OBJS) $(MODLIBS) $(SHLIBS) $(LIBC) $(LIBM); \
		$(LN) -f $(INSTSONAME) $@; \
	else \
		$(BLDSHARED) -o $@ $(LIBRARY_OBJS) $(MODLIBS) $(SHLIBS) $(LIBC) $(LIBM); \
	fi

libpython3.so:	libpython$(LDVERSION).so
	$(BLDSHARED) $(NO_AS_NEEDED) -o $@ -Wl,-h$@ $^

libpython$(LDVERSION).dylib: $(LIBRARY_OBJS)
	 $(CC) -dynamiclib -Wl,-single_module $(PY_CORE_LDFLAGS) -undefined dynamic_lookup -Wl,-install_name,$(prefix)/lib/libpython$(LDVERSION).dylib -Wl,-compatibility_version,$(VERSION) -Wl,-current_version,$(VERSION) -o $@ $(LIBRARY_OBJS) $(DTRACE_OBJS) $(SHLIBS) $(LIBC) $(LIBM); \


libpython$(VERSION).sl: $(LIBRARY_OBJS)
	$(LDSHARED) -o $@ $(LIBRARY_OBJS) $(MODLIBS) $(SHLIBS) $(LIBC) $(LIBM)

# List of exported symbols for AIX
Modules/python.exp: $(LIBRARY)
	$(srcdir)/Modules/makexp_aix $@ "$(EXPORTSFROM)" $?

# Copy up the gdb python hooks into a position where they can be automatically
# loaded by gdb during Lib/test/test_gdb.py
#
# Distributors are likely to want to install this somewhere else e.g. relative
# to the stripped DWARF data for the shared library.
gdbhooks: $(BUILDPYTHON)-gdb.py

SRC_GDB_HOOKS=$(srcdir)/Tools/gdb/libpython.py
$(BUILDPYTHON)-gdb.py: $(SRC_GDB_HOOKS)
	$(INSTALL_DATA) $(SRC_GDB_HOOKS) $(BUILDPYTHON)-gdb.py

# This rule is here for OPENSTEP/Rhapsody/MacOSX. It builds a temporary
# minimal framework (not including the Lib directory and such) in the current
# directory.
RESSRCDIR=Mac/Resources/framework
$(PYTHONFRAMEWORKDIR)/Versions/$(VERSION)/$(PYTHONFRAMEWORK): \
		$(LIBRARY) \
		$(RESSRCDIR)/Info.plist
	$(INSTALL) -d -m $(DIRMODE) $(PYTHONFRAMEWORKDIR)/Versions/$(VERSION)
	$(CC) -o $(LDLIBRARY) $(PY_CORE_LDFLAGS) -dynamiclib \
		-all_load $(LIBRARY) -Wl,-single_module \
		-install_name $(DESTDIR)$(PYTHONFRAMEWORKINSTALLDIR)/Versions/$(VERSION)/$(PYTHONFRAMEWORK) \
		-compatibility_version $(VERSION) \
		-current_version $(VERSION) \
		-framework CoreFoundation $(LIBS);
	$(INSTALL) -d -m $(DIRMODE)  \
		$(PYTHONFRAMEWORKDIR)/Versions/$(VERSION)/Resources/English.lproj
	$(INSTALL_DATA) $(RESSRCDIR)/Info.plist \
		$(PYTHONFRAMEWORKDIR)/Versions/$(VERSION)/Resources/Info.plist
	$(LN) -fsn $(VERSION) $(PYTHONFRAMEWORKDIR)/Versions/Current
	$(LN) -fsn Versions/Current/$(PYTHONFRAMEWORK) $(PYTHONFRAMEWORKDIR)/$(PYTHONFRAMEWORK)
	$(LN) -fsn Versions/Current/Resources $(PYTHONFRAMEWORKDIR)/Resources

# This rule builds the Cygwin Python DLL and import library if configured
# for a shared core library; otherwise, this rule is a noop.
$(DLLLIBRARY) libpython$(LDVERSION).dll.a: $(LIBRARY_OBJS)
	if test -n "$(DLLLIBRARY)"; then \
		$(LDSHARED) -Wl,--out-implib=$@ -o $(DLLLIBRARY) $^ \
			$(LIBS) $(MODLIBS) $(SYSLIBS); \
	else true; \
	fi


oldsharedmods: $(SHAREDMODS)


Makefile Modules/config.c: Makefile.pre \
				$(srcdir)/Modules/config.c.in \
				$(MAKESETUP) \
				$(srcdir)/Modules/Setup \
				Modules/Setup.local
	$(SHELL) $(MAKESETUP) -c $(srcdir)/Modules/config.c.in \
				-s Modules \
				Modules/Setup.local \
				$(srcdir)/Modules/Setup
	@mv config.c Modules
	@echo "The Makefile was updated, you may need to re-run make."


Programs/_testembed: Programs/_testembed.o $(LIBRARY_DEPS)
	$(LINKCC) $(PY_CORE_LDFLAGS) $(LINKFORSHARED) -o $@ Programs/_testembed.o $(BLDLIBRARY) $(LIBS) $(MODLIBS) $(SYSLIBS)

############################################################################
# Importlib

Programs/_freeze_importlib.o: Programs/_freeze_importlib.c Makefile

Programs/_freeze_importlib: Programs/_freeze_importlib.o $(LIBRARY_OBJS_OMIT_FROZEN)
	$(LINKCC) $(PY_CORE_LDFLAGS) -o $@ Programs/_freeze_importlib.o $(LIBRARY_OBJS_OMIT_FROZEN) $(LIBS) $(MODLIBS) $(SYSLIBS)

.PHONY: regen-importlib
regen-importlib: Programs/_freeze_importlib
	# Regenerate Python/importlib_external.h
	# from Lib/importlib/_bootstrap_external.py using _freeze_importlib
	./Programs/_freeze_importlib importlib._bootstrap_external \
	    $(srcdir)/Lib/importlib/_bootstrap_external.py \
	    $(srcdir)/Python/importlib_external.h.new
	$(UPDATE_FILE) $(srcdir)/Python/importlib_external.h $(srcdir)/Python/importlib_external.h.new
	# Regenerate Python/importlib.h from Lib/importlib/_bootstrap.py
	# using _freeze_importlib
	./Programs/_freeze_importlib importlib._bootstrap \
	    $(srcdir)/Lib/importlib/_bootstrap.py \
	    $(srcdir)/Python/importlib.h.new
	$(UPDATE_FILE) $(srcdir)/Python/importlib.h $(srcdir)/Python/importlib.h.new
	# Regenerate Python/importlib_zipimport.h from Lib/zipimport.py
	# using _freeze_importlib
	./Programs/_freeze_importlib zipimport \
	    $(srcdir)/Lib/zipimport.py \
	    $(srcdir)/Python/importlib_zipimport.h.new
	$(UPDATE_FILE) $(srcdir)/Python/importlib_zipimport.h $(srcdir)/Python/importlib_zipimport.h.new

regen-abidump: all
	@$(MKDIR_P) $(srcdir)/Doc/data/
	abidw "libpython$(LDVERSION).so" --no-architecture --out-file $(srcdir)/Doc/data/python$(LDVERSION).abi.new
	@$(UPDATE_FILE) $(srcdir)/Doc/data/python$(LDVERSION).abi $(srcdir)/Doc/data/python$(LDVERSION).abi.new

check-abidump: all
		abidiff $(srcdir)/Doc/data/python$(LDVERSION).abi "libpython$(LDVERSION).so" --drop-private-types --no-architecture --no-added-syms

regen-limited-abi: all
	$(RUNSHARED) ./$(BUILDPYTHON) $(srcdir)/Tools/scripts/stable_abi.py --generate-all $(srcdir)/Misc/stable_abi.txt


############################################################################
# Regenerate all generated files

regen-all: regen-opcode regen-opcode-targets regen-typeslots \
	regen-token regen-ast regen-keyword regen-importlib clinic \
	regen-pegen-metaparser regen-pegen regen-frozen
	@echo
	@echo "Note: make regen-stdlib-module-names and autoconf should be run manually"

############################################################################
# Special rules for object files

Modules/getbuildinfo.o: $(PARSER_OBJS) \
		$(OBJECT_OBJS) \
		$(PYTHON_OBJS) \
		$(MODULE_OBJS) \
		$(MODOBJS) \
		$(DTRACE_OBJS) \
		$(srcdir)/Modules/getbuildinfo.c
	$(CC) -c $(PY_CORE_CFLAGS) \
	      -DGITVERSION="\"`LC_ALL=C $(GITVERSION)`\"" \
	      -DGITTAG="\"`LC_ALL=C $(GITTAG)`\"" \
	      -DGITBRANCH="\"`LC_ALL=C $(GITBRANCH)`\"" \
	      -o $@ $(srcdir)/Modules/getbuildinfo.c

Modules/getpath.o: $(srcdir)/Modules/getpath.c Makefile
	$(CC) -c $(PY_CORE_CFLAGS) -DPYTHONPATH='"$(PYTHONPATH)"' \
		-DPREFIX='"$(prefix)"' \
		-DEXEC_PREFIX='"$(exec_prefix)"' \
		-DVERSION='"$(VERSION)"' \
		-DVPATH='"$(VPATH)"' \
		-o $@ $(srcdir)/Modules/getpath.c

Programs/python.o: $(srcdir)/Programs/python.c
	$(MAINCC) -c $(PY_CORE_CFLAGS) -o $@ $(srcdir)/Programs/python.c

Programs/_testembed.o: $(srcdir)/Programs/_testembed.c
	$(MAINCC) -c $(PY_CORE_CFLAGS) -o $@ $(srcdir)/Programs/_testembed.c

Modules/_sre.o: $(srcdir)/Modules/_sre.c $(srcdir)/Modules/sre.h $(srcdir)/Modules/sre_constants.h $(srcdir)/Modules/sre_lib.h

Modules/posixmodule.o: $(srcdir)/Modules/posixmodule.c $(srcdir)/Modules/posixmodule.h

Modules/grpmodule.o: $(srcdir)/Modules/grpmodule.c $(srcdir)/Modules/posixmodule.h

Modules/pwdmodule.o: $(srcdir)/Modules/pwdmodule.c $(srcdir)/Modules/posixmodule.h

Modules/signalmodule.o: $(srcdir)/Modules/signalmodule.c $(srcdir)/Modules/posixmodule.h

Python/dynload_shlib.o: $(srcdir)/Python/dynload_shlib.c Makefile
	$(CC) -c $(PY_CORE_CFLAGS) \
		-DSOABI='"$(SOABI)"' \
		-o $@ $(srcdir)/Python/dynload_shlib.c

Python/dynload_hpux.o: $(srcdir)/Python/dynload_hpux.c Makefile
	$(CC) -c $(PY_CORE_CFLAGS) \
		-DSHLIB_EXT='"$(EXT_SUFFIX)"' \
		-o $@ $(srcdir)/Python/dynload_hpux.c

Python/sysmodule.o: $(srcdir)/Python/sysmodule.c Makefile $(srcdir)/Include/pydtrace.h
	$(CC) -c $(PY_CORE_CFLAGS) \
		-DABIFLAGS='"$(ABIFLAGS)"' \
		$(MULTIARCH_CPPFLAGS) \
		-o $@ $(srcdir)/Python/sysmodule.c

Python/initconfig.o: $(srcdir)/Python/initconfig.c
	$(CC) -c $(PY_CORE_CFLAGS) \
		-DPLATLIBDIR='"$(PLATLIBDIR)"' \
		-o $@ $(srcdir)/Python/initconfig.c

$(IO_OBJS): $(IO_H)

.PHONY: regen-pegen-metaparser
regen-pegen-metaparser:
	@$(MKDIR_P) $(srcdir)/Tools/peg_generator/pegen
	PYTHONPATH=$(srcdir)/Tools/peg_generator $(PYTHON_FOR_REGEN) -m pegen -q python \
	$(srcdir)/Tools/peg_generator/pegen/metagrammar.gram \
	-o $(srcdir)/Tools/peg_generator/pegen/grammar_parser.py.new
	$(UPDATE_FILE) $(srcdir)/Tools/peg_generator/pegen/grammar_parser.py \
	$(srcdir)/Tools/peg_generator/pegen/grammar_parser.py.new

.PHONY: regen-pegen
regen-pegen:
	@$(MKDIR_P) $(srcdir)/Parser
	PYTHONPATH=$(srcdir)/Tools/peg_generator $(PYTHON_FOR_REGEN) -m pegen -q c \
		$(srcdir)/Grammar/python.gram \
		$(srcdir)/Grammar/Tokens \
		-o $(srcdir)/Parser/parser.new.c
	$(UPDATE_FILE) $(srcdir)/Parser/parser.c $(srcdir)/Parser/parser.new.c

.PHONY=regen-ast
regen-ast:
	# Regenerate 3 files using using Parser/asdl_c.py:
	# - Include/internal/pycore_ast.h
	# - Include/internal/pycore_ast_state.h
	# - Python/Python-ast.c
	$(MKDIR_P) $(srcdir)/Include
	$(MKDIR_P) $(srcdir)/Python
	$(PYTHON_FOR_REGEN) $(srcdir)/Parser/asdl_c.py \
		$(srcdir)/Parser/Python.asdl \
		-H $(srcdir)/Include/internal/pycore_ast.h.new \
		-I $(srcdir)/Include/internal/pycore_ast_state.h.new \
		-C $(srcdir)/Python/Python-ast.c.new

	$(UPDATE_FILE) $(srcdir)/Include/internal/pycore_ast.h $(srcdir)/Include/internal/pycore_ast.h.new
	$(UPDATE_FILE) $(srcdir)/Include/internal/pycore_ast_state.h $(srcdir)/Include/internal/pycore_ast_state.h.new
	$(UPDATE_FILE) $(srcdir)/Python/Python-ast.c $(srcdir)/Python/Python-ast.c.new

.PHONY: regen-opcode
regen-opcode:
	# Regenerate Include/opcode.h from Lib/opcode.py
	# using Tools/scripts/generate_opcode_h.py
	$(PYTHON_FOR_REGEN) $(srcdir)/Tools/scripts/generate_opcode_h.py \
		$(srcdir)/Lib/opcode.py \
		$(srcdir)/Include/opcode.h.new
	$(UPDATE_FILE) $(srcdir)/Include/opcode.h $(srcdir)/Include/opcode.h.new

.PHONY: regen-frozen
regen-frozen: Programs/_freeze_importlib
	# Regenerate code for frozen module "__hello__".
	./Programs/_freeze_importlib hello \
		$(srcdir)/Tools/freeze/flag.py \
		$(srcdir)/Python/frozen_hello.h.new
	$(UPDATE_FILE) $(srcdir)/Python/frozen_hello.h \
		$(srcdir)/Python/frozen_hello.h.new

.PHONY: regen-token
regen-token:
	# Regenerate Doc/library/token-list.inc from Grammar/Tokens
	# using Tools/scripts/generate_token.py
	$(PYTHON_FOR_REGEN) $(srcdir)/Tools/scripts/generate_token.py rst \
		$(srcdir)/Grammar/Tokens \
		$(srcdir)/Doc/library/token-list.inc
	# Regenerate Include/token.h from Grammar/Tokens
	# using Tools/scripts/generate_token.py
	$(PYTHON_FOR_REGEN) $(srcdir)/Tools/scripts/generate_token.py h \
		$(srcdir)/Grammar/Tokens \
		$(srcdir)/Include/token.h
	# Regenerate Parser/token.c from Grammar/Tokens
	# using Tools/scripts/generate_token.py
	$(PYTHON_FOR_REGEN) $(srcdir)/Tools/scripts/generate_token.py c \
		$(srcdir)/Grammar/Tokens \
		$(srcdir)/Parser/token.c
	# Regenerate Lib/token.py from Grammar/Tokens
	# using Tools/scripts/generate_token.py
	$(PYTHON_FOR_REGEN) $(srcdir)/Tools/scripts/generate_token.py py \
		$(srcdir)/Grammar/Tokens \
		$(srcdir)/Lib/token.py

.PHONY: regen-keyword
regen-keyword:
	# Regenerate Lib/keyword.py from Grammar/python.gram and Grammar/Tokens
	# using Tools/peg_generator/pegen
	PYTHONPATH=$(srcdir)/Tools/peg_generator $(PYTHON_FOR_REGEN) -m pegen.keywordgen \
		$(srcdir)/Grammar/python.gram \
		$(srcdir)/Grammar/Tokens \
		$(srcdir)/Lib/keyword.py.new
	$(UPDATE_FILE) $(srcdir)/Lib/keyword.py $(srcdir)/Lib/keyword.py.new

.PHONY: regen-stdlib-module-names
regen-stdlib-module-names: build_all Programs/_testembed
	# Regenerate Python/stdlib_module_names.h
	# using Tools/scripts/generate_stdlib_module_names.py
	$(RUNSHARED) ./$(BUILDPYTHON) \
		$(srcdir)/Tools/scripts/generate_stdlib_module_names.py \
		> $(srcdir)/Python/stdlib_module_names.h.new
	$(UPDATE_FILE) $(srcdir)/Python/stdlib_module_names.h $(srcdir)/Python/stdlib_module_names.h.new

Python/compile.o Python/symtable.o Python/ast_unparse.o Python/ast.o Python/future.o: $(srcdir)/Include/internal/pycore_ast.h

Python/getplatform.o: $(srcdir)/Python/getplatform.c
		$(CC) -c $(PY_CORE_CFLAGS) -DPLATFORM='"$(MACHDEP)"' -o $@ $(srcdir)/Python/getplatform.c

Python/importdl.o: $(srcdir)/Python/importdl.c
		$(CC) -c $(PY_CORE_CFLAGS) -I$(DLINCLDIR) -o $@ $(srcdir)/Python/importdl.c

Objects/unicodectype.o:	$(srcdir)/Objects/unicodectype.c \
				$(srcdir)/Objects/unicodetype_db.h

BYTESTR_DEPS = \
		$(srcdir)/Objects/stringlib/count.h \
		$(srcdir)/Objects/stringlib/ctype.h \
		$(srcdir)/Objects/stringlib/fastsearch.h \
		$(srcdir)/Objects/stringlib/find.h \
		$(srcdir)/Objects/stringlib/join.h \
		$(srcdir)/Objects/stringlib/partition.h \
		$(srcdir)/Objects/stringlib/split.h \
		$(srcdir)/Objects/stringlib/stringdefs.h \
		$(srcdir)/Objects/stringlib/transmogrify.h

UNICODE_DEPS = \
		$(srcdir)/Objects/stringlib/asciilib.h \
		$(srcdir)/Objects/stringlib/codecs.h \
		$(srcdir)/Objects/stringlib/count.h \
		$(srcdir)/Objects/stringlib/fastsearch.h \
		$(srcdir)/Objects/stringlib/find.h \
		$(srcdir)/Objects/stringlib/find_max_char.h \
		$(srcdir)/Objects/stringlib/localeutil.h \
		$(srcdir)/Objects/stringlib/partition.h \
		$(srcdir)/Objects/stringlib/replace.h \
		$(srcdir)/Objects/stringlib/split.h \
		$(srcdir)/Objects/stringlib/ucs1lib.h \
		$(srcdir)/Objects/stringlib/ucs2lib.h \
		$(srcdir)/Objects/stringlib/ucs4lib.h \
		$(srcdir)/Objects/stringlib/undef.h \
		$(srcdir)/Objects/stringlib/unicode_format.h \
		$(srcdir)/Objects/stringlib/unicodedefs.h

Objects/bytes_methods.o: $(srcdir)/Objects/bytes_methods.c $(BYTESTR_DEPS)
Objects/bytesobject.o: $(srcdir)/Objects/bytesobject.c $(BYTESTR_DEPS)
Objects/bytearrayobject.o: $(srcdir)/Objects/bytearrayobject.c $(BYTESTR_DEPS)

Objects/unicodeobject.o: $(srcdir)/Objects/unicodeobject.c $(UNICODE_DEPS)

Objects/odictobject.o: $(srcdir)/Objects/dict-common.h
Objects/dictobject.o: $(srcdir)/Objects/stringlib/eq.h $(srcdir)/Objects/dict-common.h
Objects/setobject.o: $(srcdir)/Objects/stringlib/eq.h

.PHONY: regen-opcode-targets
regen-opcode-targets:
	# Regenerate Python/opcode_targets.h from Lib/opcode.py
	# using Python/makeopcodetargets.py
	$(PYTHON_FOR_REGEN) $(srcdir)/Python/makeopcodetargets.py \
		$(srcdir)/Python/opcode_targets.h.new
	$(UPDATE_FILE) $(srcdir)/Python/opcode_targets.h $(srcdir)/Python/opcode_targets.h.new

Python/ceval.o: $(srcdir)/Python/opcode_targets.h $(srcdir)/Python/ceval_gil.h \
		$(srcdir)/Python/condvar.h

Python/frozen.o: $(srcdir)/Python/importlib.h $(srcdir)/Python/importlib_external.h \
		$(srcdir)/Python/importlib_zipimport.h $(srcdir)/Python/frozen_hello.h

# Generate DTrace probe macros, then rename them (PYTHON_ -> PyDTrace_) to
# follow our naming conventions. dtrace(1) uses the output filename to generate
# an include guard, so we can't use a pipeline to transform its output.
Include/pydtrace_probes.h: $(srcdir)/Include/pydtrace.d
	$(MKDIR_P) Include
	$(DTRACE) $(DFLAGS) -o $@ -h -s $<
	: sed in-place edit with POSIX-only tools
	sed 's/PYTHON_/PyDTrace_/' $@ > $@.tmp
	mv $@.tmp $@

Python/ceval.o: $(srcdir)/Include/pydtrace.h
Python/import.o: $(srcdir)/Include/pydtrace.h
Modules/gcmodule.o: $(srcdir)/Include/pydtrace.h

Python/pydtrace.o: $(srcdir)/Include/pydtrace.d $(DTRACE_DEPS)
	$(DTRACE) $(DFLAGS) -o $@ -G -s $< $(DTRACE_DEPS)

Objects/typeobject.o: Objects/typeslots.inc

.PHONY: regen-typeslots
regen-typeslots:
	# Regenerate Objects/typeslots.inc from Include/typeslotsh
	# using Objects/typeslots.py
	$(PYTHON_FOR_REGEN) $(srcdir)/Objects/typeslots.py \
		< $(srcdir)/Include/typeslots.h \
		$(srcdir)/Objects/typeslots.inc.new
	$(UPDATE_FILE) $(srcdir)/Objects/typeslots.inc $(srcdir)/Objects/typeslots.inc.new

############################################################################
# Header files

PYTHON_HEADERS= \
		$(srcdir)/Include/Python.h \
		$(srcdir)/Include/abstract.h \
		$(srcdir)/Include/bltinmodule.h \
		$(srcdir)/Include/boolobject.h \
		$(srcdir)/Include/bytearrayobject.h \
		$(srcdir)/Include/bytesobject.h \
		$(srcdir)/Include/cellobject.h \
		$(srcdir)/Include/ceval.h \
		$(srcdir)/Include/classobject.h \
		$(srcdir)/Include/code.h \
		$(srcdir)/Include/codecs.h \
		$(srcdir)/Include/compile.h \
		$(srcdir)/Include/complexobject.h \
		$(srcdir)/Include/context.h \
		$(srcdir)/Include/descrobject.h \
		$(srcdir)/Include/dictobject.h \
		$(srcdir)/Include/dynamic_annotations.h \
		$(srcdir)/Include/enumobject.h \
		$(srcdir)/Include/errcode.h \
		$(srcdir)/Include/eval.h \
		$(srcdir)/Include/fileobject.h \
		$(srcdir)/Include/fileutils.h \
		$(srcdir)/Include/floatobject.h \
		$(srcdir)/Include/frameobject.h \
		$(srcdir)/Include/funcobject.h \
		$(srcdir)/Include/genobject.h \
		$(srcdir)/Include/import.h \
		$(srcdir)/Include/interpreteridobject.h \
		$(srcdir)/Include/intrcheck.h \
		$(srcdir)/Include/iterobject.h \
		$(srcdir)/Include/listobject.h \
		$(srcdir)/Include/longintrepr.h \
		$(srcdir)/Include/longobject.h \
		$(srcdir)/Include/marshal.h \
		$(srcdir)/Include/memoryobject.h \
		$(srcdir)/Include/methodobject.h \
		$(srcdir)/Include/modsupport.h \
		$(srcdir)/Include/moduleobject.h \
		$(srcdir)/Include/namespaceobject.h \
		$(srcdir)/Include/object.h \
		$(srcdir)/Include/objimpl.h \
		$(srcdir)/Include/opcode.h \
		$(srcdir)/Include/osdefs.h \
		$(srcdir)/Include/osmodule.h \
		$(srcdir)/Include/patchlevel.h \
		$(srcdir)/Include/pycapsule.h \
		$(srcdir)/Include/pydtrace.h \
		$(srcdir)/Include/pyerrors.h \
		$(srcdir)/Include/pyframe.h \
		$(srcdir)/Include/pyhash.h \
		$(srcdir)/Include/pylifecycle.h \
		$(srcdir)/Include/pymacconfig.h \
		$(srcdir)/Include/pymacro.h \
		$(srcdir)/Include/pymath.h \
		$(srcdir)/Include/pymem.h \
		$(srcdir)/Include/pyport.h \
		$(srcdir)/Include/pystate.h \
		$(srcdir)/Include/pystrcmp.h \
		$(srcdir)/Include/pystrhex.h \
		$(srcdir)/Include/pystrtod.h \
		$(srcdir)/Include/pythonrun.h \
		$(srcdir)/Include/pythread.h \
		$(srcdir)/Include/rangeobject.h \
		$(srcdir)/Include/setobject.h \
		$(srcdir)/Include/sliceobject.h \
		$(srcdir)/Include/structmember.h \
		$(srcdir)/Include/structseq.h \
		$(srcdir)/Include/sysmodule.h \
		$(srcdir)/Include/token.h \
		$(srcdir)/Include/traceback.h \
		$(srcdir)/Include/tracemalloc.h \
		$(srcdir)/Include/tupleobject.h \
		$(srcdir)/Include/unicodeobject.h \
		$(srcdir)/Include/warnings.h \
		$(srcdir)/Include/weakrefobject.h \
		\
		pyconfig.h \
		$(PARSER_HEADERS) \
		\
		$(srcdir)/Include/cpython/abstract.h \
		$(srcdir)/Include/cpython/bytearrayobject.h \
		$(srcdir)/Include/cpython/bytesobject.h \
		$(srcdir)/Include/cpython/ceval.h \
		$(srcdir)/Include/cpython/code.h \
		$(srcdir)/Include/cpython/compile.h \
		$(srcdir)/Include/cpython/dictobject.h \
		$(srcdir)/Include/cpython/fileobject.h \
		$(srcdir)/Include/cpython/fileutils.h \
		$(srcdir)/Include/cpython/frameobject.h \
		$(srcdir)/Include/cpython/import.h \
		$(srcdir)/Include/cpython/initconfig.h \
		$(srcdir)/Include/cpython/interpreteridobject.h \
		$(srcdir)/Include/cpython/listobject.h \
		$(srcdir)/Include/cpython/methodobject.h \
		$(srcdir)/Include/cpython/object.h \
		$(srcdir)/Include/cpython/objimpl.h \
		$(srcdir)/Include/cpython/odictobject.h \
		$(srcdir)/Include/cpython/picklebufobject.h \
		$(srcdir)/Include/cpython/pyctype.h \
		$(srcdir)/Include/cpython/pydebug.h \
		$(srcdir)/Include/cpython/pyerrors.h \
		$(srcdir)/Include/cpython/pyfpe.h \
		$(srcdir)/Include/cpython/pylifecycle.h \
		$(srcdir)/Include/cpython/pymem.h \
		$(srcdir)/Include/cpython/pystate.h \
		$(srcdir)/Include/cpython/pythonrun.h \
		$(srcdir)/Include/cpython/pytime.h \
		$(srcdir)/Include/cpython/sysmodule.h \
		$(srcdir)/Include/cpython/traceback.h \
		$(srcdir)/Include/cpython/tupleobject.h \
		$(srcdir)/Include/cpython/unicodeobject.h \
		\
		$(srcdir)/Include/internal/pycore_abstract.h \
		$(srcdir)/Include/internal/pycore_accu.h \
		$(srcdir)/Include/internal/pycore_asdl.h \
		$(srcdir)/Include/internal/pycore_ast.h \
		$(srcdir)/Include/internal/pycore_ast_state.h \
		$(srcdir)/Include/internal/pycore_atomic.h \
		$(srcdir)/Include/internal/pycore_atomic_funcs.h \
		$(srcdir)/Include/internal/pycore_bitutils.h \
		$(srcdir)/Include/internal/pycore_bytes_methods.h \
		$(srcdir)/Include/internal/pycore_call.h \
		$(srcdir)/Include/internal/pycore_ceval.h \
		$(srcdir)/Include/internal/pycore_code.h \
		$(srcdir)/Include/internal/pycore_compile.h \
		$(srcdir)/Include/internal/pycore_condvar.h \
		$(srcdir)/Include/internal/pycore_context.h \
		$(srcdir)/Include/internal/pycore_dtoa.h \
		$(srcdir)/Include/internal/pycore_fileutils.h \
		$(srcdir)/Include/internal/pycore_format.h \
		$(srcdir)/Include/internal/pycore_getopt.h \
		$(srcdir)/Include/internal/pycore_gil.h \
		$(srcdir)/Include/internal/pycore_hamt.h \
		$(srcdir)/Include/internal/pycore_hashtable.h \
		$(srcdir)/Include/internal/pycore_import.h \
		$(srcdir)/Include/internal/pycore_initconfig.h \
		$(srcdir)/Include/internal/pycore_interp.h \
		$(srcdir)/Include/internal/pycore_list.h \
		$(srcdir)/Include/internal/pycore_long.h \
		$(srcdir)/Include/internal/pycore_moduleobject.h \
		$(srcdir)/Include/internal/pycore_object.h \
		$(srcdir)/Include/internal/pycore_pathconfig.h \
		$(srcdir)/Include/internal/pycore_pyarena.h \
		$(srcdir)/Include/internal/pycore_pyerrors.h \
		$(srcdir)/Include/internal/pycore_pyhash.h \
		$(srcdir)/Include/internal/pycore_pylifecycle.h \
		$(srcdir)/Include/internal/pycore_pymem.h \
		$(srcdir)/Include/internal/pycore_pystate.h \
		$(srcdir)/Include/internal/pycore_runtime.h \
		$(srcdir)/Include/internal/pycore_structseq.h \
		$(srcdir)/Include/internal/pycore_symtable.h \
		$(srcdir)/Include/internal/pycore_sysmodule.h \
		$(srcdir)/Include/internal/pycore_traceback.h \
		$(srcdir)/Include/internal/pycore_tuple.h \
		$(srcdir)/Include/internal/pycore_ucnhash.h \
		$(srcdir)/Include/internal/pycore_unionobject.h \
		$(srcdir)/Include/internal/pycore_warnings.h \
		$(DTRACE_HEADERS) \
		\
		$(srcdir)/Python/stdlib_module_names.h

$(LIBRARY_OBJS) $(MODOBJS) Programs/python.o: $(PYTHON_HEADERS)


######################################################################

TESTOPTS=	$(EXTRATESTOPTS)
TESTPYTHON=	$(RUNSHARED) ./$(BUILDPYTHON) $(TESTPYTHONOPTS)
TESTRUNNER=	$(TESTPYTHON) $(srcdir)/Tools/scripts/run_tests.py
TESTTIMEOUT=	1200

.PHONY: test testall testuniversal buildbottest pythoninfo

# Remove "test_python_*" directories of previous failed test jobs.
# Pass TESTOPTS options because it can contain --tempdir option.
cleantest: build_all
	$(TESTRUNNER) $(TESTOPTS) --cleanup

# Run a basic set of regression tests.
# This excludes some tests that are particularly resource-intensive.
test:		build_all platform
		$(TESTRUNNER) $(TESTOPTS)

# Run the full test suite twice - once without .pyc files, and once with.
# In the past, we've had problems where bugs in the marshalling or
# elsewhere caused bytecode read from .pyc files to behave differently
# than bytecode generated directly from a .py source file.  Sometimes
# the bytecode read from a .pyc file had the bug, sometimes the directly
# generated bytecode.  This is sometimes a very shy bug needing a lot of
# sample data.
testall:	build_all platform
		-find $(srcdir)/Lib -name '*.py[co]' -print | xargs rm -f
		$(TESTPYTHON) -E $(srcdir)/Lib/compileall.py
		-find $(srcdir)/Lib -name '*.py[co]' -print | xargs rm -f
		-$(TESTRUNNER) -u all $(TESTOPTS)
		$(TESTRUNNER) -u all $(TESTOPTS)

# Run the test suite for both architectures in a Universal build on OSX.
# Must be run on an Intel box.
testuniversal:	build_all platform
		@if [ `arch` != 'i386' ]; then \
			echo "This can only be used on OSX/i386" ;\
			exit 1 ;\
		fi
		$(TESTRUNNER) -u all $(TESTOPTS)
		$(RUNSHARED) /usr/libexec/oah/translate \
			./$(BUILDPYTHON) -E -m test -j 0 -u all $(TESTOPTS)

# Like testall, but with only one pass and without multiple processes.
# Run an optional script to include information about the build environment.
buildbottest:	build_all platform
		-@if which pybuildbot.identify >/dev/null 2>&1; then \
			pybuildbot.identify "CC='$(CC)'" "CXX='$(CXX)'"; \
		fi
		$(TESTRUNNER) -j 1 -u all -W --slowest --fail-env-changed --timeout=$(TESTTIMEOUT) $(TESTOPTS)

pythoninfo: build_all
		$(RUNSHARED) ./$(BUILDPYTHON) -m test.pythoninfo

QUICKTESTOPTS=	$(TESTOPTS) -x test_subprocess test_io test_lib2to3 \
		test_multibytecodec test_urllib2_localnet test_itertools \
		test_multiprocessing_fork test_multiprocessing_spawn \
		test_multiprocessing_forkserver \
		test_mailbox test_socket test_poll \
		test_select test_zipfile test_concurrent_futures
quicktest:	build_all platform
		$(TESTRUNNER) $(QUICKTESTOPTS)

# SSL tests
.PHONY: multisslcompile multissltest
multisslcompile: build_all
	$(RUNSHARED) ./$(BUILDPYTHON) $(srcdir)/Tools/ssl/multissltests.py --steps=modules

multissltest: build_all
	$(RUNSHARED) ./$(BUILDPYTHON) $(srcdir)/Tools/ssl/multissltests.py

install:  commoninstall bininstall maninstall 
	if test "x$(ENSUREPIP)" != "xno"  ; then \
		case $(ENSUREPIP) in \
			upgrade) ensurepip="--upgrade" ;; \
			install|*) ensurepip="" ;; \
		esac; \
		$(RUNSHARED) $(PY_BUILD_ENVIRON) $(PYTHON_FOR_BUILD) -m ensurepip \
			$$ensurepip --root=$(DESTDIR)/ ; \
	fi

altinstall: commoninstall
	if test "x$(ENSUREPIP)" != "xno"  ; then \
		case $(ENSUREPIP) in \
			upgrade) ensurepip="--altinstall --upgrade" ;; \
			install|*) ensurepip="--altinstall" ;; \
		esac; \
		$(RUNSHARED) $(PY_BUILD_ENVIRON) $(PYTHON_FOR_BUILD) -m ensurepip \
			$$ensurepip --root=$(DESTDIR)/ ; \
	fi

commoninstall:  check-clean-src  \
		altbininstall libinstall inclinstall libainstall \
		sharedinstall oldsharedinstall altmaninstall \
		

# Install shared libraries enabled by Setup
DESTDIRS=	$(exec_prefix) $(LIBDIR) $(BINLIBDEST) $(DESTSHARED)

oldsharedinstall: $(DESTSHARED) $(SHAREDMODS)
		@for i in X $(SHAREDMODS); do \
		  if test $$i != X; then \
		    echo $(INSTALL_SHARED) $$i $(DESTSHARED)/`basename $$i`; \
		    $(INSTALL_SHARED) $$i $(DESTDIR)$(DESTSHARED)/`basename $$i`; \
		  fi; \
		done

$(DESTSHARED):
		@for i in $(DESTDIRS); \
		do \
			if test ! -d $(DESTDIR)$$i; then \
				echo "Creating directory $$i"; \
				$(INSTALL) -d -m $(DIRMODE) $(DESTDIR)$$i; \
			else    true; \
			fi; \
		done

# Install the interpreter with $(VERSION) affixed
# This goes into $(exec_prefix)
altbininstall: $(BUILDPYTHON) 
	@for i in $(BINDIR) $(LIBDIR); \
	do \
		if test ! -d $(DESTDIR)$$i; then \
			echo "Creating directory $$i"; \
			$(INSTALL) -d -m $(DIRMODE) $(DESTDIR)$$i; \
		else	true; \
		fi; \
	done
	if test "$(PYTHONFRAMEWORKDIR)" = "no-framework" ; then \
		$(INSTALL_PROGRAM) $(BUILDPYTHON) $(DESTDIR)$(BINDIR)/python$(LDVERSION)$(EXE); \
	else \
		$(INSTALL_PROGRAM) $(STRIPFLAG) Mac/pythonw $(DESTDIR)$(BINDIR)/python$(LDVERSION)$(EXE); \
	fi
	-if test "$(VERSION)" != "$(LDVERSION)"; then \
		if test -f $(DESTDIR)$(BINDIR)/python$(VERSION)$(EXE) -o -h $(DESTDIR)$(BINDIR)/python$(VERSION)$(EXE); \
		then rm -f $(DESTDIR)$(BINDIR)/python$(VERSION)$(EXE); \
		fi; \
		(cd $(DESTDIR)$(BINDIR); $(LN) python$(LDVERSION)$(EXE) python$(VERSION)$(EXE)); \
	fi
	@if test "$(PY_ENABLE_SHARED)" = 1 -o "$(STATIC_LIBPYTHON)" = 1; then \
		if test -f $(LDLIBRARY) && test "$(PYTHONFRAMEWORKDIR)" = "no-framework" ; then \
			if test -n "$(DLLLIBRARY)" ; then \
				$(INSTALL_SHARED) $(DLLLIBRARY) $(DESTDIR)$(BINDIR); \
			else \
				$(INSTALL_SHARED) $(LDLIBRARY) $(DESTDIR)$(LIBDIR)/$(INSTSONAME); \
				if test $(LDLIBRARY) != $(INSTSONAME); then \
					(cd $(DESTDIR)$(LIBDIR); $(LN) -sf $(INSTSONAME) $(LDLIBRARY)) \
				fi \
			fi; \
			if test -n "$(PY3LIBRARY)"; then \
				$(INSTALL_SHARED) $(PY3LIBRARY) $(DESTDIR)$(LIBDIR)/$(PY3LIBRARY); \
			fi; \
		else	true; \
		fi; \
	fi
	if test "x$(LIPO_32BIT_FLAGS)" != "x" ; then \
		rm -f $(DESTDIR)$(BINDIR)python$(VERSION)-32$(EXE); \
		lipo $(LIPO_32BIT_FLAGS) \
			-output $(DESTDIR)$(BINDIR)/python$(VERSION)-32$(EXE) \
			$(DESTDIR)$(BINDIR)/python$(VERSION)$(EXE); \
	fi
	if test "x$(LIPO_INTEL64_FLAGS)" != "x" ; then \
		rm -f $(DESTDIR)$(BINDIR)python$(VERSION)-intel64$(EXE); \
		lipo $(LIPO_INTEL64_FLAGS) \
			-output $(DESTDIR)$(BINDIR)/python$(VERSION)-intel64$(EXE) \
			$(DESTDIR)$(BINDIR)/python$(VERSION)$(EXE); \
	fi

bininstall: altbininstall
	if test ! -d $(DESTDIR)$(LIBPC); then \
		echo "Creating directory $(LIBPC)"; \
		$(INSTALL) -d -m $(DIRMODE) $(DESTDIR)$(LIBPC); \
	fi
	-if test -f $(DESTDIR)$(BINDIR)/python3$(EXE) -o -h $(DESTDIR)$(BINDIR)/python3$(EXE); \
	then rm -f $(DESTDIR)$(BINDIR)/python3$(EXE); \
	else true; \
	fi
	(cd $(DESTDIR)$(BINDIR); $(LN) -s python$(VERSION)$(EXE) python3$(EXE))
	-if test "$(VERSION)" != "$(LDVERSION)"; then \
		rm -f $(DESTDIR)$(BINDIR)/python$(VERSION)-config; \
		(cd $(DESTDIR)$(BINDIR); $(LN) -s python$(LDVERSION)-config python$(VERSION)-config); \
		rm -f $(DESTDIR)$(LIBPC)/python-$(LDVERSION).pc; \
		(cd $(DESTDIR)$(LIBPC); $(LN) -s python-$(VERSION).pc python-$(LDVERSION).pc); \
		rm -f $(DESTDIR)$(LIBPC)/python-$(LDVERSION)-embed.pc; \
		(cd $(DESTDIR)$(LIBPC); $(LN) -s python-$(VERSION)-embed.pc python-$(LDVERSION)-embed.pc); \
	fi
	-rm -f $(DESTDIR)$(BINDIR)/python3-config
	(cd $(DESTDIR)$(BINDIR); $(LN) -s python$(VERSION)-config python3-config)
	-rm -f $(DESTDIR)$(LIBPC)/python3.pc
	(cd $(DESTDIR)$(LIBPC); $(LN) -s python-$(VERSION).pc python3.pc)
	-rm -f $(DESTDIR)$(LIBPC)/python3-embed.pc
	(cd $(DESTDIR)$(LIBPC); $(LN) -s python-$(VERSION)-embed.pc python3-embed.pc)
	-rm -f $(DESTDIR)$(BINDIR)/idle3
	(cd $(DESTDIR)$(BINDIR); $(LN) -s idle$(VERSION) idle3)
	-rm -f $(DESTDIR)$(BINDIR)/pydoc3
	(cd $(DESTDIR)$(BINDIR); $(LN) -s pydoc$(VERSION) pydoc3)
	-rm -f $(DESTDIR)$(BINDIR)/2to3
	(cd $(DESTDIR)$(BINDIR); $(LN) -s 2to3-$(VERSION) 2to3)
	if test "x$(LIPO_32BIT_FLAGS)" != "x" ; then \
		rm -f $(DESTDIR)$(BINDIR)/python3-32$(EXE); \
		(cd $(DESTDIR)$(BINDIR); $(LN) -s python$(VERSION)-32$(EXE) python3-32$(EXE)) \
	fi
	if test "x$(LIPO_INTEL64_FLAGS)" != "x" ; then \
		rm -f $(DESTDIR)$(BINDIR)/python3-intel64$(EXE); \
		(cd $(DESTDIR)$(BINDIR); $(LN) -s python$(VERSION)-intel64$(EXE) python3-intel64$(EXE)) \
	fi

# Install the versioned manual page
altmaninstall:
	@for i in $(MANDIR) $(MANDIR)/man1; \
	do \
		if test ! -d $(DESTDIR)$$i; then \
			echo "Creating directory $$i"; \
			$(INSTALL) -d -m $(DIRMODE) $(DESTDIR)$$i; \
		else	true; \
		fi; \
	done
	$(INSTALL_DATA) $(srcdir)/Misc/python.man \
		$(DESTDIR)$(MANDIR)/man1/python$(VERSION).1

# Install the unversioned manual page
maninstall:	altmaninstall
	-rm -f $(DESTDIR)$(MANDIR)/man1/python3.1
	(cd $(DESTDIR)$(MANDIR)/man1; $(LN) -s python$(VERSION).1 python3.1)

# Install the library
XMLLIBSUBDIRS=  xml xml/dom xml/etree xml/parsers xml/sax
LIBSUBDIRS=	asyncio \
		collections \
		concurrent concurrent/futures \
		csv \
		ctypes ctypes/macholib \
		curses \
		dbm \
		distutils distutils/command \
		email email/mime \
		encodings \
		ensurepip ensurepip/_bundled \
		html \
		http \
		idlelib idlelib/Icons \
		importlib importlib/metadata \
		json \
		lib2to3 lib2to3/fixes lib2to3/pgen2 \
		logging \
		multiprocessing multiprocessing/dummy \
		pydoc_data \
		site-packages \
		sqlite3 \
		tkinter \
		turtledemo \
		unittest \
		urllib \
		venv venv/scripts venv/scripts/common venv/scripts/posix \
		wsgiref \
		$(XMLLIBSUBDIRS) \
		xmlrpc \
		zoneinfo
TESTSUBDIRS=	ctypes/test \
		distutils/tests \
		idlelib/idle_test \
		lib2to3/tests \
		lib2to3/tests/data \
		lib2to3/tests/data/fixers \
		lib2to3/tests/data/fixers/myfixes \
		sqlite3/test \
		test test/audiodata \
		test/capath test/cjkencodings \
		test/data test/decimaltestdata \
		test/dtracedata test/eintrdata \
		test/encoded_modules test/imghdrdata \
		test/libregrtest test/sndhdrdata \
		test/subprocessdata test/support \
		test/test_asyncio \
		test/test_email test/test_email/data \
		test/test_import \
		test/test_import/data \
		test/test_import/data/circular_imports \
		test/test_import/data/circular_imports/subpkg \
		test/test_import/data/package \
		test/test_import/data/package2 \
		test/test_import/data/unwritable \
		test/test_importlib \
		test/test_importlib/builtin \
		test/test_importlib/data \
		test/test_importlib/data01 \
		test/test_importlib/data01/subdirectory \
		test/test_importlib/data02 \
		test/test_importlib/data02/one \
		test/test_importlib/data02/two \
		test/test_importlib/data03 \
		test/test_importlib/data03/namespace \
		test/test_importlib/data03/namespace/portion1 \
		test/test_importlib/data03/namespace/portion2 \
		test/test_importlib/extension \
		test/test_importlib/frozen \
		test/test_importlib/import_ \
		test/test_importlib/namespace_pkgs \
		test/test_importlib/namespace_pkgs/both_portions \
		test/test_importlib/namespace_pkgs/both_portions/foo \
		test/test_importlib/namespace_pkgs/module_and_namespace_package \
		test/test_importlib/namespace_pkgs/module_and_namespace_package/a_test \
		test/test_importlib/namespace_pkgs/not_a_namespace_pkg \
		test/test_importlib/namespace_pkgs/not_a_namespace_pkg/foo \
		test/test_importlib/namespace_pkgs/portion1 \
		test/test_importlib/namespace_pkgs/portion1/foo \
		test/test_importlib/namespace_pkgs/portion2 \
		test/test_importlib/namespace_pkgs/portion2/foo \
		test/test_importlib/namespace_pkgs/project1 \
		test/test_importlib/namespace_pkgs/project1/parent \
		test/test_importlib/namespace_pkgs/project1/parent/child \
		test/test_importlib/namespace_pkgs/project2 \
		test/test_importlib/namespace_pkgs/project2/parent \
		test/test_importlib/namespace_pkgs/project2/parent/child \
		test/test_importlib/namespace_pkgs/project3 \
		test/test_importlib/namespace_pkgs/project3/parent \
		test/test_importlib/namespace_pkgs/project3/parent/child \
		test/test_importlib/namespacedata01 \
		test/test_importlib/partial \
		test/test_importlib/source \
		test/test_importlib/zipdata01 \
		test/test_importlib/zipdata02 \
		test/test_json \
		test/test_peg_generator \
		test/test_tools \
		test/test_warnings test/test_warnings/data \
		test/test_zoneinfo test/test_zoneinfo/data \
		test/tracedmodules \
		test/typinganndata \
		test/xmltestdata test/xmltestdata/c14n-20 \
		test/ziptestdata \
		tkinter/test tkinter/test/test_tkinter \
		tkinter/test/test_ttk \
		unittest/test unittest/test/testmock

TEST_MODULES=yes
libinstall:	build_all $(srcdir)/Modules/xxmodule.c
	@for i in $(SCRIPTDIR) $(LIBDEST); \
	do \
		if test ! -d $(DESTDIR)$$i; then \
			echo "Creating directory $$i"; \
			$(INSTALL) -d -m $(DIRMODE) $(DESTDIR)$$i; \
		else	true; \
		fi; \
	done
	@if test "$(TEST_MODULES)" = yes; then \
		subdirs="$(LIBSUBDIRS) $(TESTSUBDIRS)"; \
	else \
		subdirs="$(LIBSUBDIRS)"; \
	fi; \
	for d in $$subdirs; \
	do \
		a=$(srcdir)/Lib/$$d; \
		if test ! -d $$a; then continue; else true; fi; \
		b=$(LIBDEST)/$$d; \
		if test ! -d $(DESTDIR)$$b; then \
			echo "Creating directory $$b"; \
			$(INSTALL) -d -m $(DIRMODE) $(DESTDIR)$$b; \
		else	true; \
		fi; \
	done
	@for i in $(srcdir)/Lib/*.py; \
	do \
		if test -x $$i; then \
			$(INSTALL_SCRIPT) $$i $(DESTDIR)$(LIBDEST); \
			echo $(INSTALL_SCRIPT) $$i $(LIBDEST); \
		else \
			$(INSTALL_DATA) $$i $(DESTDIR)$(LIBDEST); \
			echo $(INSTALL_DATA) $$i $(LIBDEST); \
		fi; \
	done
	@if test "$(TEST_MODULES)" = yes; then \
		subdirs="$(LIBSUBDIRS) $(TESTSUBDIRS)"; \
	else \
		subdirs="$(LIBSUBDIRS)"; \
	fi; \
	for d in $$subdirs; \
	do \
		a=$(srcdir)/Lib/$$d; \
		if test ! -d $$a; then continue; else true; fi; \
		if test `ls $$a | wc -l` -lt 1; then continue; fi; \
		b=$(LIBDEST)/$$d; \
		for i in $$a/*; \
		do \
			case $$i in \
			*CVS) ;; \
			*.py[co]) ;; \
			*.orig) ;; \
			*~) ;; \
			*) \
				if test -d $$i; then continue; fi; \
				if test -x $$i; then \
				    echo $(INSTALL_SCRIPT) $$i $$b; \
				    $(INSTALL_SCRIPT) $$i $(DESTDIR)$$b; \
				else \
				    echo $(INSTALL_DATA) $$i $$b; \
				    $(INSTALL_DATA) $$i $(DESTDIR)$$b; \
				fi;; \
			esac; \
		done; \
	done
	$(INSTALL_DATA) `cat pybuilddir.txt`/_sysconfigdata_$(ABIFLAGS)_$(MACHDEP)_$(MULTIARCH).py \
		$(DESTDIR)$(LIBDEST); \
	$(INSTALL_DATA) $(srcdir)/LICENSE $(DESTDIR)$(LIBDEST)/LICENSE.txt
	if test -d $(DESTDIR)$(LIBDEST)/distutils/tests; then \
		$(INSTALL_DATA) $(srcdir)/Modules/xxmodule.c \
			$(DESTDIR)$(LIBDEST)/distutils/tests ; \
	fi
	-PYTHONPATH=$(DESTDIR)$(LIBDEST)  $(RUNSHARED) \
		$(PYTHON_FOR_BUILD) -Wi $(DESTDIR)$(LIBDEST)/compileall.py \
		-j0 -d $(LIBDEST) -f \
		-x 'bad_coding|badsyntax|site-packages|lib2to3/tests/data' \
		$(DESTDIR)$(LIBDEST)
	-PYTHONPATH=$(DESTDIR)$(LIBDEST) $(RUNSHARED) \
		$(PYTHON_FOR_BUILD) -Wi -O $(DESTDIR)$(LIBDEST)/compileall.py \
		-j0 -d $(LIBDEST) -f \
		-x 'bad_coding|badsyntax|site-packages|lib2to3/tests/data' \
		$(DESTDIR)$(LIBDEST)
	-PYTHONPATH=$(DESTDIR)$(LIBDEST) $(RUNSHARED) \
		$(PYTHON_FOR_BUILD) -Wi -OO $(DESTDIR)$(LIBDEST)/compileall.py \
		-j0 -d $(LIBDEST) -f \
		-x 'bad_coding|badsyntax|site-packages|lib2to3/tests/data' \
		$(DESTDIR)$(LIBDEST)
	-PYTHONPATH=$(DESTDIR)$(LIBDEST) $(RUNSHARED) \
		$(PYTHON_FOR_BUILD) -Wi $(DESTDIR)$(LIBDEST)/compileall.py \
		-j0 -d $(LIBDEST)/site-packages -f \
		-x badsyntax $(DESTDIR)$(LIBDEST)/site-packages
	-PYTHONPATH=$(DESTDIR)$(LIBDEST) $(RUNSHARED) \
		$(PYTHON_FOR_BUILD) -Wi -O $(DESTDIR)$(LIBDEST)/compileall.py \
		-j0 -d $(LIBDEST)/site-packages -f \
		-x badsyntax $(DESTDIR)$(LIBDEST)/site-packages
	-PYTHONPATH=$(DESTDIR)$(LIBDEST) $(RUNSHARED) \
		$(PYTHON_FOR_BUILD) -Wi -OO $(DESTDIR)$(LIBDEST)/compileall.py \
		-j0 -d $(LIBDEST)/site-packages -f \
		-x badsyntax $(DESTDIR)$(LIBDEST)/site-packages
	-PYTHONPATH=$(DESTDIR)$(LIBDEST) $(RUNSHARED) \
		$(PYTHON_FOR_BUILD) -m lib2to3.pgen2.driver $(DESTDIR)$(LIBDEST)/lib2to3/Grammar.txt
	-PYTHONPATH=$(DESTDIR)$(LIBDEST) $(RUNSHARED) \
		$(PYTHON_FOR_BUILD) -m lib2to3.pgen2.driver $(DESTDIR)$(LIBDEST)/lib2to3/PatternGrammar.txt

# bpo-21536: Misc/python-config.sh is generated in the build directory
# from $(srcdir)Misc/python-config.sh.in.
python-config: $(srcdir)/Misc/python-config.in Misc/python-config.sh
	@ # Substitution happens here, as the completely-expanded BINDIR
	@ # is not available in configure
	sed -e "s,@EXENAME@,$(BINDIR)/python$(LDVERSION)$(EXE)," < $(srcdir)/Misc/python-config.in >python-config.py
	@ # Replace makefile compat. variable references with shell script compat. ones; $(VAR) -> ${VAR}
	LC_ALL=C sed -e 's,\$$(\([A-Za-z0-9_]*\)),\$$\{\1\},g' < Misc/python-config.sh >python-config
	@ # On Darwin, always use the python version of the script, the shell
	@ # version doesn't use the compiler customizations that are provided
	@ # in python (_osx_support.py).
	@if test `uname -s` = Darwin; then \
		cp python-config.py python-config; \
	fi


# Install the include files
INCLDIRSTOMAKE=$(INCLUDEDIR) $(CONFINCLUDEDIR) $(INCLUDEPY) $(CONFINCLUDEPY)
inclinstall:
	@for i in $(INCLDIRSTOMAKE); \
	do \
		if test ! -d $(DESTDIR)$$i; then \
			echo "Creating directory $$i"; \
			$(INSTALL) -d -m $(DIRMODE) $(DESTDIR)$$i; \
		else	true; \
		fi; \
	done
	@if test ! -d $(DESTDIR)$(INCLUDEPY)/cpython; then \
		echo "Creating directory $(DESTDIR)$(INCLUDEPY)/cpython"; \
		$(INSTALL) -d -m $(DIRMODE) $(DESTDIR)$(INCLUDEPY)/cpython; \
	else	true; \
	fi
	@if test ! -d $(DESTDIR)$(INCLUDEPY)/internal; then \
		echo "Creating directory $(DESTDIR)$(INCLUDEPY)/internal"; \
		$(INSTALL) -d -m $(DIRMODE) $(DESTDIR)$(INCLUDEPY)/internal; \
	else	true; \
	fi
	@for i in $(srcdir)/Include/*.h; \
	do \
		echo $(INSTALL_DATA) $$i $(INCLUDEPY); \
		$(INSTALL_DATA) $$i $(DESTDIR)$(INCLUDEPY); \
	done
	@for i in $(srcdir)/Include/cpython/*.h; \
	do \
		echo $(INSTALL_DATA) $$i $(INCLUDEPY)/cpython; \
		$(INSTALL_DATA) $$i $(DESTDIR)$(INCLUDEPY)/cpython; \
	done
	@for i in $(srcdir)/Include/internal/*.h; \
	do \
		echo $(INSTALL_DATA) $$i $(INCLUDEPY)/internal; \
		$(INSTALL_DATA) $$i $(DESTDIR)$(INCLUDEPY)/internal; \
	done
	$(INSTALL_DATA) pyconfig.h $(DESTDIR)$(CONFINCLUDEPY)/pyconfig.h

# Install the library and miscellaneous stuff needed for extending/embedding
# This goes into $(exec_prefix)
LIBPL=		$(prefix)/lib/python3.10/config-$(VERSION)$(ABIFLAGS)-x86_64-linux-gnu

# pkgconfig directory
LIBPC=		$(LIBDIR)/pkgconfig

libainstall:	build_all python-config
	@for i in $(LIBDIR) $(LIBPL) $(LIBPC) $(BINDIR); \
	do \
		if test ! -d $(DESTDIR)$$i; then \
			echo "Creating directory $$i"; \
			$(INSTALL) -d -m $(DIRMODE) $(DESTDIR)$$i; \
		else	true; \
		fi; \
	done
	@if test "$(STATIC_LIBPYTHON)" = 1; then \
		if test -d $(LIBRARY); then :; else \
			if test "$(PYTHONFRAMEWORKDIR)" = no-framework; then \
				if test "$(SHLIB_SUFFIX)" = .dll; then \
					$(INSTALL_DATA) $(LDLIBRARY) $(DESTDIR)$(LIBPL) ; \
				else \
					$(INSTALL_DATA) $(LIBRARY) $(DESTDIR)$(LIBPL)/$(LIBRARY) ; \
				fi; \
			else \
				echo Skip install of $(LIBRARY) - use make frameworkinstall; \
			fi; \
		fi; \
		$(INSTALL_DATA) Programs/python.o $(DESTDIR)$(LIBPL)/python.o; \
	fi
	$(INSTALL_DATA) Modules/config.c $(DESTDIR)$(LIBPL)/config.c
	$(INSTALL_DATA) $(srcdir)/Modules/config.c.in $(DESTDIR)$(LIBPL)/config.c.in
	$(INSTALL_DATA) Makefile $(DESTDIR)$(LIBPL)/Makefile
	$(INSTALL_DATA) $(srcdir)/Modules/Setup $(DESTDIR)$(LIBPL)/Setup
	$(INSTALL_DATA) Modules/Setup.local $(DESTDIR)$(LIBPL)/Setup.local
	$(INSTALL_DATA) Misc/python.pc $(DESTDIR)$(LIBPC)/python-$(VERSION).pc
	$(INSTALL_DATA) Misc/python-embed.pc $(DESTDIR)$(LIBPC)/python-$(VERSION)-embed.pc
	$(INSTALL_SCRIPT) $(srcdir)/Modules/makesetup $(DESTDIR)$(LIBPL)/makesetup
	$(INSTALL_SCRIPT) $(srcdir)/install-sh $(DESTDIR)$(LIBPL)/install-sh
	$(INSTALL_SCRIPT) python-config.py $(DESTDIR)$(LIBPL)/python-config.py
	$(INSTALL_SCRIPT) python-config $(DESTDIR)$(BINDIR)/python$(LDVERSION)-config
	@if [ -s Modules/python.exp -a \
		"`echo $(MACHDEP) | sed 's/^\(...\).*/\1/'`" = "aix" ]; then \
		echo; echo "Installing support files for building shared extension modules on AIX:"; \
		$(INSTALL_DATA) Modules/python.exp		\
				$(DESTDIR)$(LIBPL)/python.exp;		\
		echo; echo "$(LIBPL)/python.exp";		\
		$(INSTALL_SCRIPT) $(srcdir)/Modules/makexp_aix	\
				$(DESTDIR)$(LIBPL)/makexp_aix;		\
		echo "$(LIBPL)/makexp_aix";			\
		$(INSTALL_SCRIPT) Modules/ld_so_aix	\
				$(DESTDIR)$(LIBPL)/ld_so_aix;		\
		echo "$(LIBPL)/ld_so_aix";			\
		echo; echo "See Misc/README.AIX for details.";	\
	else true; \
	fi

# Install the dynamically loadable modules
# This goes into $(exec_prefix)
sharedinstall: sharedmods
	$(RUNSHARED) $(PY_BUILD_ENVIRON) $(PYTHON_FOR_BUILD) $(srcdir)/setup.py install \
	   	--prefix=$(prefix) \
		--install-scripts=$(BINDIR) \
		--install-platlib=$(DESTSHARED) \
		--root=$(DESTDIR)/
	-rm $(DESTDIR)$(DESTSHARED)/_sysconfigdata_$(ABIFLAGS)_$(MACHDEP)_$(MULTIARCH).py
	-rm -r $(DESTDIR)$(DESTSHARED)/__pycache__

# Here are a couple of targets for MacOSX again, to install a full
# framework-based Python. frameworkinstall installs everything, the
# subtargets install specific parts. Much of the actual work is offloaded to
# the Makefile in Mac
#
#
# This target is here for backward compatibility, previous versions of Python
# hadn't integrated framework installation in the normal install process.
frameworkinstall: install

# On install, we re-make the framework
# structure in the install location, /Library/Frameworks/ or the argument to
# --enable-framework. If --enable-framework has been specified then we have
# automatically set prefix to the location deep down in the framework, so we
# only have to cater for the structural bits of the framework.

frameworkinstallframework: frameworkinstallstructure install frameworkinstallmaclib

frameworkinstallstructure:	$(LDLIBRARY)
	@if test "$(PYTHONFRAMEWORKDIR)" = no-framework; then \
		echo Not configured with --enable-framework; \
		exit 1; \
	else true; \
	fi
	@for i in $(prefix)/Resources/English.lproj $(prefix)/lib; do\
		if test ! -d $(DESTDIR)$$i; then \
			echo "Creating directory $(DESTDIR)$$i"; \
			$(INSTALL) -d -m $(DIRMODE) $(DESTDIR)$$i; \
		else	true; \
		fi; \
	done
	$(LN) -fsn include/python$(LDVERSION) $(DESTDIR)$(prefix)/Headers
	sed 's/%VERSION%/'"`$(RUNSHARED) ./$(BUILDPYTHON) -c 'import platform; print(platform.python_version())'`"'/g' < $(RESSRCDIR)/Info.plist > $(DESTDIR)$(prefix)/Resources/Info.plist
	$(LN) -fsn $(VERSION) $(DESTDIR)$(PYTHONFRAMEWORKINSTALLDIR)/Versions/Current
	$(LN) -fsn Versions/Current/$(PYTHONFRAMEWORK) $(DESTDIR)$(PYTHONFRAMEWORKINSTALLDIR)/$(PYTHONFRAMEWORK)
	$(LN) -fsn Versions/Current/Headers $(DESTDIR)$(PYTHONFRAMEWORKINSTALLDIR)/Headers
	$(LN) -fsn Versions/Current/Resources $(DESTDIR)$(PYTHONFRAMEWORKINSTALLDIR)/Resources
	$(INSTALL_SHARED) $(LDLIBRARY) $(DESTDIR)$(PYTHONFRAMEWORKPREFIX)/$(LDLIBRARY)

# This installs Mac/Lib into the framework
# Install a number of symlinks to keep software that expects a normal unix
# install (which includes python-config) happy.
frameworkinstallmaclib:
	$(LN) -fs "../../../$(PYTHONFRAMEWORK)" "$(DESTDIR)$(LIBPL)/libpython$(LDVERSION).a"
	$(LN) -fs "../../../$(PYTHONFRAMEWORK)" "$(DESTDIR)$(LIBPL)/libpython$(LDVERSION).dylib"
	$(LN) -fs "../../../$(PYTHONFRAMEWORK)" "$(DESTDIR)$(LIBPL)/libpython$(VERSION).a"
	$(LN) -fs "../../../$(PYTHONFRAMEWORK)" "$(DESTDIR)$(LIBPL)/libpython$(VERSION).dylib"
	$(LN) -fs "../$(PYTHONFRAMEWORK)" "$(DESTDIR)$(prefix)/lib/libpython$(LDVERSION).dylib"
	$(LN) -fs "../$(PYTHONFRAMEWORK)" "$(DESTDIR)$(prefix)/lib/libpython$(VERSION).dylib"

# This installs the IDE, the Launcher and other apps into /Applications
frameworkinstallapps:
	cd Mac && $(MAKE) installapps DESTDIR="$(DESTDIR)"

# Build the bootstrap executable that will spawn the interpreter inside
# an app bundle within the framework.  This allows the interpreter to
# run OS X GUI APIs.
frameworkpythonw:
	cd Mac && $(MAKE) pythonw

# This installs the python* and other bin symlinks in $prefix/bin or in
# a bin directory relative to the framework root
frameworkinstallunixtools:
	cd Mac && $(MAKE) installunixtools DESTDIR="$(DESTDIR)"

frameworkaltinstallunixtools:
	cd Mac && $(MAKE) altinstallunixtools DESTDIR="$(DESTDIR)"

# This installs the Tools into the applications directory.
# It is not part of a normal frameworkinstall
frameworkinstallextras:
	cd Mac && $(MAKE) installextras DESTDIR="$(DESTDIR)"

# Build the toplevel Makefile
Makefile.pre: $(srcdir)/Makefile.pre.in config.status
	CONFIG_FILES=Makefile.pre CONFIG_HEADERS= $(SHELL) config.status
	$(MAKE) -f Makefile.pre Makefile

# Run the configure script.
config.status:	$(srcdir)/configure
	$(SHELL) $(srcdir)/configure $(CONFIG_ARGS)

.PRECIOUS: config.status $(BUILDPYTHON) Makefile Makefile.pre

# Some make's put the object file in the current directory
.c.o:
	$(CC) -c $(PY_CORE_CFLAGS) -o $@ $<

# bpo-30104: dtoa.c uses union to cast double to unsigned long[2]. clang 4.0
# with -O2 or higher and strict aliasing miscompiles the ratio() function
# causing rounding issues. Compile dtoa.c using -fno-strict-aliasing on clang.
# https://bugs.llvm.org//show_bug.cgi?id=31928
Python/dtoa.o: Python/dtoa.c
	$(CC) -c $(PY_CORE_CFLAGS) $(CFLAGS_ALIASING) -o $@ $<

# Run reindent on the library
reindent:
	./$(BUILDPYTHON) $(srcdir)/Tools/scripts/reindent.py -r $(srcdir)/Lib

# Rerun configure with the same options as it was run last time,
# provided the config.status script exists
recheck:
	$(SHELL) config.status --recheck
	$(SHELL) config.status

# Regenerate configure and pyconfig.h.in
.PHONY: autoconf
autoconf:
	# Regenerate the configure script from configure.ac using autoconf
	(cd $(srcdir); autoconf -Wall)
	# Regenerate pyconfig.h.in from configure.ac using autoheader
	(cd $(srcdir); autoheader -Wall)

# See https://github.com/tiran/cpython_autoconf container
.PHONY: regen-configure
regen-configure:
	@if command -v podman >/dev/null; then RUNTIME="podman"; else RUNTIME="docker"; fi; \
	if ! command -v $$RUNTIME; then echo "$@ needs either Podman or Docker container runtime." >&2; exit 1; fi; \
	if command -v selinuxenabled >/dev/null && selinuxenabled; then OPT=":Z"; fi; \
	# Manifest corresponds with tag '269' \
	CPYTHON_AUTOCONF_MANIFEST="sha256:f370fee95eefa3d57b00488bce4911635411fa83e2d293ced8cf8a3674ead939" \
	CMD="$$RUNTIME run --rm --pull=missing -v $(abs_srcdir):/src$$OPT quay.io/tiran/cpython_autoconf@$$CPYTHON_AUTOCONF_MANIFEST"; \
	echo $$CMD; \
	$$CMD || exit $?

# Create a tags file for vi
tags::
	ctags -w $(srcdir)/Include/*.h $(srcdir)/Include/cpython/*.h $(srcdir)/Include/internal/*.h
	for i in $(SRCDIRS); do ctags -f tags -w -a $(srcdir)/$$i/*.[ch]; done
	ctags -f tags -w -a $(srcdir)/Modules/_ctypes/*.[ch]
	find $(srcdir)/Lib -type f -name "*.py" -not -name "test_*.py" -not -path "*/test/*" -not -path "*/tests/*" -not -path "*/*_test/*" | ctags -f tags -w -a -L -
	LC_ALL=C sort -o tags tags

# Create a tags file for GNU Emacs
TAGS::
	cd $(srcdir); \
	etags Include/*.h Include/cpython/*.h Include/internal/*.h; \
	for i in $(SRCDIRS); do etags -a $$i/*.[ch]; done
	etags -a $(srcdir)/Modules/_ctypes/*.[ch]
	find $(srcdir)/Lib -type f -name "*.py" -not -name "test_*.py" -not -path "*/test/*" -not -path "*/tests/*" -not -path "*/*_test/*" | etags - -a

# Sanitation targets -- clean leaves libraries, executables and tags
# files, which clobber removes as well
pycremoval:
	-find $(srcdir) -depth -name '__pycache__' -exec rm -rf {} ';'
	-find $(srcdir) -name '*.py[co]' -exec rm -f {} ';'

rmtestturds:
	-rm -f *BAD *GOOD *SKIPPED
	-rm -rf OUT
	-rm -f *.TXT
	-rm -f *.txt
	-rm -f gb-18030-2000.xml

docclean:
	$(MAKE) -C $(srcdir)/Doc clean

# like the 'clean' target but retain the profile guided optimization (PGO)
# data.  The PGO data is only valid if source code remains unchanged.
clean-retain-profile: pycremoval
	find . -name '*.[oa]' -exec rm -f {} ';'
	find . -name '*.s[ol]' -exec rm -f {} ';'
	find . -name '*.so.[0-9]*.[0-9]*' -exec rm -f {} ';'
	find . -name '*.lst' -exec rm -f {} ';'
	find build -name 'fficonfig.h' -exec rm -f {} ';' || true
	find build -name '*.py' -exec rm -f {} ';' || true
	find build -name '*.py[co]' -exec rm -f {} ';' || true
	-rm -f pybuilddir.txt
	-rm -f Lib/lib2to3/*Grammar*.pickle
	-rm -f Programs/_testembed Programs/_freeze_importlib
	-find build -type f -a ! -name '*.gc??' -exec rm -f {} ';'
	-rm -f Include/pydtrace_probes.h
	-rm -f profile-gen-stamp

profile-removal:
	find . -name '*.gc??' -exec rm -f {} ';'
	find . -name '*.profclang?' -exec rm -f {} ';'
	find . -name '*.dyn' -exec rm -f {} ';'
	rm -f $(COVERAGE_INFO)
	rm -rf $(COVERAGE_REPORT)
	rm -f profile-run-stamp

clean: clean-retain-profile
	@if test profile-opt = profile-opt; then \
		rm -f profile-gen-stamp profile-clean-stamp; \
		$(MAKE) profile-removal; \
	fi

clobber: clean
	-rm -f $(BUILDPYTHON) $(LIBRARY) $(LDLIBRARY) $(DLLLIBRARY) \
		tags TAGS \
		config.cache config.log pyconfig.h Modules/config.c
	-rm -rf build platform
	-rm -rf $(PYTHONFRAMEWORKDIR)
	-rm -f python-config.py python-config

# Make things extra clean, before making a distribution:
# remove all generated files, even Makefile[.pre]
# Keep configure and Python-ast.[ch], it's possible they can't be generated
distclean: clobber docclean
	for file in $(srcdir)/Lib/test/data/* ; do \
	    if test "$$file" != "$(srcdir)/Lib/test/data/README"; then rm "$$file"; fi; \
	done
	-rm -f core Makefile Makefile.pre config.status Modules/Setup.local \
		Modules/ld_so_aix Modules/python.exp Misc/python.pc \
		Misc/python-embed.pc Misc/python-config.sh
	-rm -f python*-gdb.py
	# Issue #28258: set LC_ALL to avoid issues with Estonian locale.
	# Expansion is performed here by shell (spawned by make) itself before
	# arguments are passed to find. So LC_ALL=C must be set as a separate
	# command.
	LC_ALL=C; find $(srcdir)/[a-zA-Z]* '(' -name '*.fdc' -o -name '*~' \
				     -o -name '[@,#]*' -o -name '*.old' \
				     -o -name '*.orig' -o -name '*.rej' \
				     -o -name '*.bak' ')' \
				     -exec rm -f {} ';'

# Check that all symbols exported by libpython start with "Py" or "_Py"
smelly: build_all
	$(RUNSHARED) ./$(BUILDPYTHON) $(srcdir)/Tools/scripts/smelly.py

# Find files with funny names
funny:
	find $(SUBDIRS) $(SUBDIRSTOO) \
		-type d \
		-o -name '*.[chs]' \
		-o -name '*.py' \
		-o -name '*.pyw' \
		-o -name '*.dat' \
		-o -name '*.el' \
		-o -name '*.fd' \
		-o -name '*.in' \
		-o -name '*.gif' \
		-o -name '*.txt' \
		-o -name '*.xml' \
		-o -name '*.xbm' \
		-o -name '*.xpm' \
		-o -name '*.uue' \
		-o -name '*.decTest' \
		-o -name '*.tmCommand' \
		-o -name '*.tmSnippet' \
		-o -name 'Setup' \
		-o -name 'Setup.*' \
		-o -name README \
		-o -name NEWS \
		-o -name HISTORY \
		-o -name Makefile \
		-o -name ChangeLog \
		-o -name .hgignore \
		-o -name MANIFEST \
		-o -print

# Perform some verification checks on any modified files.
patchcheck: build_all
	$(RUNSHARED) ./$(BUILDPYTHON) $(srcdir)/Tools/scripts/patchcheck.py

check-limited-abi: all
	$(RUNSHARED) ./$(BUILDPYTHON) $(srcdir)/Tools/scripts/stable_abi.py --all $(srcdir)/Misc/stable_abi.txt

.PHONY: update-config
update-config:
	curl -sL -o config.guess 'https://git.savannah.gnu.org/gitweb/?p=config.git;a=blob_plain;f=config.guess;hb=HEAD'
	curl -sL -o config.sub 'https://git.savannah.gnu.org/gitweb/?p=config.git;a=blob_plain;f=config.sub;hb=HEAD'
	chmod +x config.guess config.sub

# Dependencies

Python/thread.o:  $(srcdir)/Python/thread_nt.h $(srcdir)/Python/thread_pthread.h $(srcdir)/Python/condvar.h

# Declare targets that aren't real files
.PHONY: all build_all sharedmods check-clean-src oldsharedmods test quicktest
.PHONY: install altinstall oldsharedinstall bininstall altbininstall
.PHONY: maninstall libinstall inclinstall libainstall sharedinstall
.PHONY: frameworkinstall frameworkinstallframework frameworkinstallstructure
.PHONY: frameworkinstallmaclib frameworkinstallapps frameworkinstallunixtools
.PHONY: frameworkaltinstallunixtools recheck clean clobber distclean
.PHONY: smelly funny patchcheck touch altmaninstall commoninstall
.PHONY: clean-retain-profile profile-removal run_profile_task
.PHONY: build_all_generate_profile build_all_merge_profile
.PHONY: gdbhooks

# IF YOU PUT ANYTHING HERE IT WILL GO AWAY
# Local Variables:
# mode: makefile
# End:

# Rules appended by makesetup

Modules/posixmodule.o: $(srcdir)/Modules/posixmodule.c; $(CC) $(PY_BUILTIN_MODULE_CFLAGS)  -DPy_BUILD_CORE_BUILTIN -I$(srcdir)/Include/internal -c $(srcdir)/Modules/posixmodule.c -o Modules/posixmodule.o
Modules/posix$(EXT_SUFFIX):  Modules/posixmodule.o; $(BLDSHARED)  Modules/posixmodule.o   -o Modules/posix$(EXT_SUFFIX)
Modules/errnomodule.o: $(srcdir)/Modules/errnomodule.c; $(CC) $(PY_BUILTIN_MODULE_CFLAGS)  -c $(srcdir)/Modules/errnomodule.c -o Modules/errnomodule.o
Modules/errno$(EXT_SUFFIX):  Modules/errnomodule.o; $(BLDSHARED)  Modules/errnomodule.o   -o Modules/errno$(EXT_SUFFIX)
Modules/pwdmodule.o: $(srcdir)/Modules/pwdmodule.c; $(CC) $(PY_BUILTIN_MODULE_CFLAGS)  -c $(srcdir)/Modules/pwdmodule.c -o Modules/pwdmodule.o
Modules/pwd$(EXT_SUFFIX):  Modules/pwdmodule.o; $(BLDSHARED)  Modules/pwdmodule.o   -o Modules/pwd$(EXT_SUFFIX)
Modules/_sre.o: $(srcdir)/Modules/_sre.c; $(CC) $(PY_BUILTIN_MODULE_CFLAGS)  -DPy_BUILD_CORE_BUILTIN -c $(srcdir)/Modules/_sre.c -o Modules/_sre.o
Modules/_sre$(EXT_SUFFIX):  Modules/_sre.o; $(BLDSHARED)  Modules/_sre.o   -o Modules/_sre$(EXT_SUFFIX)
Modules/_codecsmodule.o: $(srcdir)/Modules/_codecsmodule.c; $(CC) $(PY_BUILTIN_MODULE_CFLAGS)  -c $(srcdir)/Modules/_codecsmodule.c -o Modules/_codecsmodule.o
Modules/_codecs$(EXT_SUFFIX):  Modules/_codecsmodule.o; $(BLDSHARED)  Modules/_codecsmodule.o   -o Modules/_codecs$(EXT_SUFFIX)
Modules/_weakref.o: $(srcdir)/Modules/_weakref.c; $(CC) $(PY_BUILTIN_MODULE_CFLAGS)  -c $(srcdir)/Modules/_weakref.c -o Modules/_weakref.o
Modules/_weakref$(EXT_SUFFIX):  Modules/_weakref.o; $(BLDSHARED)  Modules/_weakref.o   -o Modules/_weakref$(EXT_SUFFIX)
Modules/_functoolsmodule.o: $(srcdir)/Modules/_functoolsmodule.c; $(CC) $(PY_BUILTIN_MODULE_CFLAGS)  -DPy_BUILD_CORE_BUILTIN -I$(srcdir)/Include/internal -c $(srcdir)/Modules/_functoolsmodule.c -o Modules/_functoolsmodule.o
Modules/_functools$(EXT_SUFFIX):  Modules/_functoolsmodule.o; $(BLDSHARED)  Modules/_functoolsmodule.o   -o Modules/_functools$(EXT_SUFFIX)
Modules/_operator.o: $(srcdir)/Modules/_operator.c; $(CC) $(PY_BUILTIN_MODULE_CFLAGS)  -DPy_BUILD_CORE_BUILTIN -c $(srcdir)/Modules/_operator.c -o Modules/_operator.o
Modules/_operator$(EXT_SUFFIX):  Modules/_operator.o; $(BLDSHARED)  Modules/_operator.o   -o Modules/_operator$(EXT_SUFFIX)
Modules/_collectionsmodule.o: $(srcdir)/Modules/_collectionsmodule.c; $(CC) $(PY_BUILTIN_MODULE_CFLAGS)  -c $(srcdir)/Modules/_collectionsmodule.c -o Modules/_collectionsmodule.o
Modules/_collections$(EXT_SUFFIX):  Modules/_collectionsmodule.o; $(BLDSHARED)  Modules/_collectionsmodule.o   -o Modules/_collections$(EXT_SUFFIX)
Modules/_abc.o: $(srcdir)/Modules/_abc.c; $(CC) $(PY_BUILTIN_MODULE_CFLAGS)  -DPy_BUILD_CORE_BUILTIN -c $(srcdir)/Modules/_abc.c -o Modules/_abc.o
Modules/_abc$(EXT_SUFFIX):  Modules/_abc.o; $(BLDSHARED)  Modules/_abc.o   -o Modules/_abc$(EXT_SUFFIX)
Modules/itertoolsmodule.o: $(srcdir)/Modules/itertoolsmodule.c; $(CC) $(PY_BUILTIN_MODULE_CFLAGS)  -c $(srcdir)/Modules/itertoolsmodule.c -o Modules/itertoolsmodule.o
Modules/itertools$(EXT_SUFFIX):  Modules/itertoolsmodule.o; $(BLDSHARED)  Modules/itertoolsmodule.o   -o Modules/itertools$(EXT_SUFFIX)
Modules/atexitmodule.o: $(srcdir)/Modules/atexitmodule.c; $(CC) $(PY_BUILTIN_MODULE_CFLAGS)  -c $(srcdir)/Modules/atexitmodule.c -o Modules/atexitmodule.o
Modules/atexit$(EXT_SUFFIX):  Modules/atexitmodule.o; $(BLDSHARED)  Modules/atexitmodule.o   -o Modules/atexit$(EXT_SUFFIX)
Modules/signalmodule.o: $(srcdir)/Modules/signalmodule.c; $(CC) $(PY_BUILTIN_MODULE_CFLAGS)  -DPy_BUILD_CORE_BUILTIN -I$(srcdir)/Include/internal -c $(srcdir)/Modules/signalmodule.c -o Modules/signalmodule.o
Modules/_signal$(EXT_SUFFIX):  Modules/signalmodule.o; $(BLDSHARED)  Modules/signalmodule.o   -o Modules/_signal$(EXT_SUFFIX)
Modules/_stat.o: $(srcdir)/Modules/_stat.c; $(CC) $(PY_BUILTIN_MODULE_CFLAGS)  -c $(srcdir)/Modules/_stat.c -o Modules/_stat.o
Modules/_stat$(EXT_SUFFIX):  Modules/_stat.o; $(BLDSHARED)  Modules/_stat.o   -o Modules/_stat$(EXT_SUFFIX)
Modules/timemodule.o: $(srcdir)/Modules/timemodule.c; $(CC) $(PY_BUILTIN_MODULE_CFLAGS)  -DPy_BUILD_CORE_BUILTIN -I$(srcdir)/Include/internal -c $(srcdir)/Modules/timemodule.c -o Modules/timemodule.o
Modules/time$(EXT_SUFFIX):  Modules/timemodule.o; $(BLDSHARED)  Modules/timemodule.o   -o Modules/time$(EXT_SUFFIX)
Modules/_threadmodule.o: $(srcdir)/Modules/_threadmodule.c; $(CC) $(PY_BUILTIN_MODULE_CFLAGS)  -DPy_BUILD_CORE_BUILTIN -I$(srcdir)/Include/internal -c $(srcdir)/Modules/_threadmodule.c -o Modules/_threadmodule.o
Modules/_thread$(EXT_SUFFIX):  Modules/_threadmodule.o; $(BLDSHARED)  Modules/_threadmodule.o   -o Modules/_thread$(EXT_SUFFIX)
Modules/_localemodule.o: $(srcdir)/Modules/_localemodule.c; $(CC) $(PY_BUILTIN_MODULE_CFLAGS)  -DPy_BUILD_CORE_BUILTIN -c $(srcdir)/Modules/_localemodule.c -o Modules/_localemodule.o
Modules/_locale$(EXT_SUFFIX):  Modules/_localemodule.o; $(BLDSHARED)  Modules/_localemodule.o   -o Modules/_locale$(EXT_SUFFIX)
Modules/_iomodule.o: $(srcdir)/Modules/_io/_iomodule.c; $(CC) $(PY_BUILTIN_MODULE_CFLAGS)  -DPy_BUILD_CORE_BUILTIN -I$(srcdir)/Include/internal -I$(srcdir)/Modules/_io -c $(srcdir)/Modules/_io/_iomodule.c -o Modules/_iomodule.o
Modules/iobase.o: $(srcdir)/Modules/_io/iobase.c; $(CC) $(PY_BUILTIN_MODULE_CFLAGS)  -DPy_BUILD_CORE_BUILTIN -I$(srcdir)/Include/internal -I$(srcdir)/Modules/_io -c $(srcdir)/Modules/_io/iobase.c -o Modules/iobase.o
Modules/fileio.o: $(srcdir)/Modules/_io/fileio.c; $(CC) $(PY_BUILTIN_MODULE_CFLAGS)  -DPy_BUILD_CORE_BUILTIN -I$(srcdir)/Include/internal -I$(srcdir)/Modules/_io -c $(srcdir)/Modules/_io/fileio.c -o Modules/fileio.o
Modules/bytesio.o: $(srcdir)/Modules/_io/bytesio.c; $(CC) $(PY_BUILTIN_MODULE_CFLAGS)  -DPy_BUILD_CORE_BUILTIN -I$(srcdir)/Include/internal -I$(srcdir)/Modules/_io -c $(srcdir)/Modules/_io/bytesio.c -o Modules/bytesio.o
Modules/bufferedio.o: $(srcdir)/Modules/_io/bufferedio.c; $(CC) $(PY_BUILTIN_MODULE_CFLAGS)  -DPy_BUILD_CORE_BUILTIN -I$(srcdir)/Include/internal -I$(srcdir)/Modules/_io -c $(srcdir)/Modules/_io/bufferedio.c -o Modules/bufferedio.o
Modules/textio.o: $(srcdir)/Modules/_io/textio.c; $(CC) $(PY_BUILTIN_MODULE_CFLAGS)  -DPy_BUILD_CORE_BUILTIN -I$(srcdir)/Include/internal -I$(srcdir)/Modules/_io -c $(srcdir)/Modules/_io/textio.c -o Modules/textio.o
Modules/stringio.o: $(srcdir)/Modules/_io/stringio.c; $(CC) $(PY_BUILTIN_MODULE_CFLAGS)  -DPy_BUILD_CORE_BUILTIN -I$(srcdir)/Include/internal -I$(srcdir)/Modules/_io -c $(srcdir)/Modules/_io/stringio.c -o Modules/stringio.o
Modules/_io$(EXT_SUFFIX):  Modules/_iomodule.o Modules/iobase.o Modules/fileio.o Modules/bytesio.o Modules/bufferedio.o Modules/textio.o Modules/stringio.o; $(BLDSHARED)  Modules/_iomodule.o Modules/iobase.o Modules/fileio.o Modules/bytesio.o Modules/bufferedio.o Modules/textio.o Modules/stringio.o   -o Modules/_io$(EXT_SUFFIX)
Modules/faulthandler.o: $(srcdir)/Modules/faulthandler.c; $(CC) $(PY_BUILTIN_MODULE_CFLAGS)  -c $(srcdir)/Modules/faulthandler.c -o Modules/faulthandler.o
Modules/faulthandler$(EXT_SUFFIX):  Modules/faulthandler.o; $(BLDSHARED)  Modules/faulthandler.o   -o Modules/faulthandler$(EXT_SUFFIX)
Modules/_tracemalloc.o: $(srcdir)/Modules/_tracemalloc.c; $(CC) $(PY_BUILTIN_MODULE_CFLAGS)  -c $(srcdir)/Modules/_tracemalloc.c -o Modules/_tracemalloc.o
Modules/_tracemalloc$(EXT_SUFFIX):  Modules/_tracemalloc.o; $(BLDSHARED)  Modules/_tracemalloc.o   -o Modules/_tracemalloc$(EXT_SUFFIX)
Modules/symtablemodule.o: $(srcdir)/Modules/symtablemodule.c; $(CC) $(PY_BUILTIN_MODULE_CFLAGS)  -c $(srcdir)/Modules/symtablemodule.c -o Modules/symtablemodule.o
Modules/_symtable$(EXT_SUFFIX):  Modules/symtablemodule.o; $(BLDSHARED)  Modules/symtablemodule.o   -o Modules/_symtable$(EXT_SUFFIX)
Modules/xxsubtype.o: $(srcdir)/Modules/xxsubtype.c; $(CC) $(PY_BUILTIN_MODULE_CFLAGS)  -c $(srcdir)/Modules/xxsubtype.c -o Modules/xxsubtype.o
Modules/xxsubtype$(EXT_SUFFIX):  Modules/xxsubtype.o; $(BLDSHARED)  Modules/xxsubtype.o   -o Modules/xxsubtype$(EXT_SUFFIX)
