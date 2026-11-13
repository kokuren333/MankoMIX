// mmx_processor.h -- internal processor interface of the MankoMIX native core.
//
// SPDX-License-Identifier: Apache-2.0
//
// Every processor (own or ported) implements mmx::Processor and publishes a
// static mmx::ProcessorSpec. The C ABI layer (mankomix_dsp.cpp) owns
// parameter bookkeeping (id lookup, clamping, storage); processors only see
// validated parameter indices and in-range values.
//
// Realtime rules for implementations:
//   - process() must not allocate, lock, throw or perform IO. All state is
//     held in fixed-size members sized by kMaxChannels.
//   - process() must be block-size independent: state that the original
//     plugin updated once per host block must be updated on a fixed
//     sample-count grid instead (see Console7 ports).
//   - No randomness. Ported Airwindows code seeds its per-channel xorshift
//     state ("fpd") with fixed constants via fpd_seed().
#ifndef MMX_PROCESSOR_H
#define MMX_PROCESSOR_H

#include <cstdint>

#include "mankomix_dsp.h"

namespace mmx {

constexpr int kMaxChannels = MMX_MAX_CHANNELS;
constexpr int kMaxParams = 16;

// Airwindows commit the ported processors were taken from
// (third_party/airwindows/ORIGIN.md).
constexpr const char* kAirwindowsCommit = "94cb6793893027fb418ffac7cdbfcb9b4c82aadb";

struct ParamSpec {
    const char* id;           // stable parameter id
    const char* unit;         // "dB", "dBFS", "linear", "norm" (0..1 control), "bipolar"
    double min_value;
    double max_value;
    double default_value;
    const char* description;
};

struct OriginSpec {
    const char* source;       // "airwindows" or "mankomix"
    const char* plugin;       // original plugin name (empty for own code)
    const char* license;      // SPDX id
    const char* files;        // original file names, comma separated
};

class Processor {
public:
    Processor(double sample_rate, int channels) : sample_rate_(sample_rate), channels_(channels) {}
    virtual ~Processor() = default;
    Processor(const Processor&) = delete;
    Processor& operator=(const Processor&) = delete;

    // `index` is valid, `value` already clamped into [min, max].
    virtual void set_param(int index, double value) = 0;
    // Restore the freshly-created signal state; parameters are kept.
    virtual void reset() = 0;
    // In-place planar processing of channels_ channels.
    virtual void process(double* const* ch, int64_t frames) = 0;
    virtual int latency() const { return 0; }

protected:
    double sample_rate_;
    int channels_;
};

struct ProcessorSpec {
    const char* id;           // stable processor id used by mmx_create()
    const char* type;         // abstract processor type (docs/SPEC.md 6.5.2)
    const char* role;         // finer role, e.g. "channel_drive", "console_buss"
    const char* name;
    const char* summary;
    OriginSpec origin;
    const ParamSpec* params;
    int num_params;
    bool block_ok;            // block processing supported (realtime suitable)
    int latency_samples;      // nominal latency (instances report exact value)
    Processor* (*create)(double sample_rate, int channels);
};

// Fixed, non-zero per-channel seed for the Airwindows "fpd" xorshift state.
// Replaces the original rand() seeding so output is reproducible.
inline uint32_t fpd_seed(int channel) {
    uint32_t s = 0x9E3779B9u ^ (static_cast<uint32_t>(channel + 1) * 0x85EBCA6Bu);
    s ^= s >> 16;
    s *= 0x7FEB352Du;
    s ^= s >> 15;
    if (s < 16386u) s += 16386u;  // the original requires fpd >= 16386
    return s;
}

// One xorshift32 step, exactly as in the Airwindows dither block.
inline void fpd_advance(uint32_t& fpd) {
    fpd ^= fpd << 13;
    fpd ^= fpd >> 17;
    fpd ^= fpd << 5;
}

// Registry (registry.cpp).
const ProcessorSpec* const* registry(int* count);

}  // namespace mmx

#endif  // MMX_PROCESSOR_H
