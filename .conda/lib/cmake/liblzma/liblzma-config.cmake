include(CMakeFindDependencyMacro)
set(THREADS_PREFER_PTHREAD_FLAG TRUE)
find_dependency(Threads)

include("${CMAKE_CURRENT_LIST_DIR}/liblzma-targets.cmake")

if(NOT TARGET LibLZMA::LibLZMA)
    # Be compatible with the spelling used by the FindLibLZMA module. This
    # doesn't use ALIAS because it would make CMake resolve LibLZMA::LibLZMA
    # to liblzma::liblzma instead of keeping the original spelling. Keeping
    # the original spelling is important for good FindLibLZMA compatibility.
    add_library(LibLZMA::LibLZMA INTERFACE IMPORTED)
    set_target_properties(LibLZMA::LibLZMA PROPERTIES
                          INTERFACE_LINK_LIBRARIES liblzma::liblzma)
endif()

