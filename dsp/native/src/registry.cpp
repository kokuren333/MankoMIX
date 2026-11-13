// registry.cpp -- list of processors compiled into the native core.
//
// SPDX-License-Identifier: Apache-2.0
//
// Order is not part of the ABI; callers look processors up by id.
// Processor ids and parameter ids are stable: never rename or remove one;
// add new processors / parameters instead.
#include "mmx_processor.h"

namespace mmx {

extern const ProcessorSpec kPurestDriveSpec;
extern const ProcessorSpec kClipOnly2Spec;
extern const ProcessorSpec kConsole7ChannelSpec;
extern const ProcessorSpec kConsole7BussSpec;
extern const ProcessorSpec kPressure4Spec;

namespace {
const ProcessorSpec* const kRegistry[] = {
    &kPurestDriveSpec,
    &kClipOnly2Spec,
    &kConsole7ChannelSpec,
    &kConsole7BussSpec,
    &kPressure4Spec,
};
}  // namespace

const ProcessorSpec* const* registry(int* count) {
    *count = static_cast<int>(sizeof(kRegistry) / sizeof(kRegistry[0]));
    return kRegistry;
}

}  // namespace mmx
