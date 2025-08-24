#                          __  __            _
#                       ___\ \/ /_ __   __ _| |_
#                      / _ \\  /| '_ \ / _` | __|
#                     |  __//  \| |_) | (_| | |_
#                      \___/_/\_\ .__/ \__,_|\__|
#                               |_| XML parser
#
# Copyright (c) 2019 Expat development team
# Licensed under the MIT license:
#
# Permission is  hereby granted,  free of charge,  to any  person obtaining
# a  copy  of  this  software   and  associated  documentation  files  (the
# "Software"),  to  deal in  the  Software  without restriction,  including
# without  limitation the  rights  to use,  copy,  modify, merge,  publish,
# distribute, sublicense, and/or sell copies of the Software, and to permit
# persons  to whom  the Software  is  furnished to  do so,  subject to  the
# following conditions:
#
# The above copyright  notice and this permission notice  shall be included
# in all copies or substantial portions of the Software.
#
# THE  SOFTWARE  IS  PROVIDED  "AS  IS",  WITHOUT  WARRANTY  OF  ANY  KIND,
# EXPRESS  OR IMPLIED,  INCLUDING  BUT  NOT LIMITED  TO  THE WARRANTIES  OF
# MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN
# NO EVENT SHALL THE AUTHORS OR  COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM,
# DAMAGES OR  OTHER LIABILITY, WHETHER  IN AN  ACTION OF CONTRACT,  TORT OR
# OTHERWISE, ARISING FROM, OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE
# USE OR OTHER DEALINGS IN THE SOFTWARE.
#
if(NOT _expat_config_included)
    # Protect against multiple inclusion
    set(_expat_config_included TRUE)


include("${CMAKE_CURRENT_LIST_DIR}/expat.cmake")


####### Expanded from @PACKAGE_INIT@ by configure_package_config_file() #######
####### Any changes to this file will be overwritten by the next CMake run ####
####### The input file was expat-config.cmake.in                            ########

get_filename_component(PACKAGE_PREFIX_DIR "${CMAKE_CURRENT_LIST_DIR}/../../../" ABSOLUTE)

macro(set_and_check _var _file)
  set(${_var} "${_file}")
  if(NOT EXISTS "${_file}")
    message(FATAL_ERROR "File or directory ${_file} referenced by variable ${_var} does not exist !")
  endif()
endmacro()

macro(check_required_components _NAME)
  foreach(comp ${${_NAME}_FIND_COMPONENTS})
    if(NOT ${_NAME}_${comp}_FOUND)
      if(${_NAME}_FIND_REQUIRED_${comp})
        set(${_NAME}_FOUND FALSE)
      endif()
    endif()
  endforeach()
endmacro()

####################################################################################

#
# Supported components
#
macro(expat_register_component _NAME _AVAILABE)
    set(expat_${_NAME}_FOUND ${_AVAILABE})
endmacro()

expat_register_component(attr_info          OFF)
expat_register_component(dtd                ON)
expat_register_component(large_size         OFF)
expat_register_component(min_size           OFF)
expat_register_component(ns                 ON)

if(1024)
    expat_register_component(context_bytes  ON)
else()
    expat_register_component(context_bytes  OFF)
endif()

if("char" STREQUAL "char")
    expat_register_component(char           ON)
    expat_register_component(ushort         OFF)
    expat_register_component(wchar_t        OFF)
elseif("char" STREQUAL "ushort")
    expat_register_component(char           OFF)
    expat_register_component(ushort         ON)
    expat_register_component(wchar_t        OFF)
elseif("char" STREQUAL "wchar_t")
    expat_register_component(char           OFF)
    expat_register_component(ushort         OFF)
    expat_register_component(wchar_t        ON)
endif()

check_required_components(expat)


endif(NOT _expat_config_included)
