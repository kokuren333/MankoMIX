# MankoMIX native DSP core (docs/SPEC.md 3.2, 3.3, 14.2).
# C++17, C ABI, no dependencies beyond the C++ standard library.
#
# Usually driven by tools/build_native.py. Manual use:
#   cmake -S dsp/native -B dsp/build/cmake -DCMAKE_BUILD_TYPE=Release
#   cmake --build dsp/build/cmake --config Release
cmake_minimum_required(VERSION 3.15)

if(POLICY CMP0091)
  cmake_policy(SET CMP0091 NEW)  # select the MSVC runtime via CMAKE_MSVC_RUNTIME_LIBRARY
endif()

project(mankomix_dsp VERSION 0.1.0 LANGUAGES CXX)

if(NOT CMAKE_BUILD_TYPE AND NOT CMAKE_CONFIGURATION_TYPES)
  set(CMAKE_BUILD_TYPE Release CACHE STRING "Build type" FORCE)
endif()

# Ported third-party sources (MIT) live in third_party/ with their license text.
set(MMX_AIRWINDOWS_DIR "${CMAKE_CURRENT_SOURCE_DIR}/../../third_party/airwindows"
    CACHE PATH "Directory holding the ported Airwindows sources")

add_library(mankomix_dsp SHARED
  src/mankomix_dsp.cpp
  src/registry.cpp
  ${MMX_AIRWINDOWS_DIR}/src/purest_drive.cpp
  ${MMX_AIRWINDOWS_DIR}/src/clip_only2.cpp
  ${MMX_AIRWINDOWS_DIR}/src/console7_channel.cpp
  ${MMX_AIRWINDOWS_DIR}/src/console7_buss.cpp
  ${MMX_AIRWINDOWS_DIR}/src/pressure4.cpp
)

target_include_directories(mankomix_dsp
  PUBLIC  ${CMAKE_CURRENT_SOURCE_DIR}/include
  PRIVATE ${CMAKE_CURRENT_SOURCE_DIR}/src
)
target_compile_features(mankomix_dsp PRIVATE cxx_std_17)
set_target_properties(mankomix_dsp PROPERTIES
  CXX_STANDARD 17
  CXX_STANDARD_REQUIRED ON
  CXX_EXTENSIONS OFF
  CXX_VISIBILITY_PRESET hidden
  VISIBILITY_INLINES_HIDDEN ON
  PREFIX ""                      # same file stem on every OS: mankomix_dsp.{dll,so,dylib}
  OUTPUT_NAME mankomix_dsp
)
target_compile_definitions(mankomix_dsp PRIVATE MMX_BUILDING_LIBRARY _USE_MATH_DEFINES)

# Determinism: no fast-math, no FMA contraction, so the floating-point result
# follows the source order of operations.
if(MSVC)
  set_property(TARGET mankomix_dsp PROPERTY MSVC_RUNTIME_LIBRARY "MultiThreaded$<$<CONFIG:Debug>:Debug>")
  # /fp:precise does not contract into FMA unless /fp:contract is given (VS 2022+).
  target_compile_options(mankomix_dsp PRIVATE /W4 /fp:precise /utf-8 /EHsc)
else()
  target_compile_options(mankomix_dsp PRIVATE -Wall -Wextra -fno-fast-math -ffp-contract=off)
endif()
