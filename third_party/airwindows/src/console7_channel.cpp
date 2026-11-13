// console7_channel.cpp -- Airwindows Console7Channel ported to the MankoMIX native core.
//
// SPDX-License-Identifier: MIT
// Original work: Console7Channel by Chris Johnson (airwindows).
//   Copyright (c) 2016 airwindows, Airwindows uses the MIT license.
//   https://github.com/airwindows/airwindows
//   commit 94cb6793893027fb418ffac7cdbfcb9b4c82aadb
//   plugins/LinuxVST/src/Console7Channel/Console7ChannelProc.cpp (processDoubleReplacing)
//   plugins/LinuxVST/src/Console7Channel/Console7Channel.cpp, Console7Channel.h
// License text: third_party/airwindows/LICENSE. Origin: third_party/airwindows/ORIGIN.md.
//
// Console7Channel is the encode half of the Console7 summing pair: put it on
// every channel (or on the 2mix) and Console7Buss after the sum.
//
// Changes for MankoMIX (the per-sample algorithm is unchanged):
//   - VST shell removed; stereo L/R code generalized to N channels (one shared
//     fader chase, per-channel biquad state as in the original).
//   - Block-size independence: the original runs its fader-chase setup
//     (chasespeed doubling and clamping to the host block length, latching
//     the fader value) once per host block. Here it runs on a fixed virtual
//     host block of kVirtualBlock = 512 frames counted internally, so output
//     equals the original running in a host with 512-frame blocks no matter
//     how the caller splits the signal.
//   - The 20 kHz lowpass frequency ratio is clamped to 0.49 of the sample
//     rate (only matters below ~40.8 kHz, where the original would be unstable).
//   - fpd seeded with fixed constants (mmx::fpd_seed); used only by the
//     original denormal guard. No dither is added (the dither line is
//     commented out in the original double path).
#include <cmath>

#include "mmx_processor.h"

namespace mmx {
namespace {

constexpr double kPi = 3.14159265358979323846;
constexpr int kVirtualBlock = 512;

const ParamSpec kParams[] = {
    {"fader", "norm", 0.0, 1.0, 0.772,
     "Channel fader (original knob). 0.772 = unity for a full-scale sine through the Console7 pair."},
};

class Console7Channel final : public Processor {
public:
    Console7Channel(double sr, int ch) : Processor(sr, ch) {
        double freq = 20000.0 / sample_rate_;
        if (freq > 0.49) freq = 0.49;
        biquadA[0] = freq;
        biquadA[1] = 1.618033988749894848204586;
        const double K = std::tan(kPi * biquadA[0]);  // lowpass
        const double norm = 1.0 / (1.0 + K / biquadA[1] + K * K);
        biquadA[2] = K * K * norm;
        biquadA[3] = 2.0 * biquadA[2];
        biquadA[4] = biquadA[2];
        biquadA[5] = 2.0 * (K * K - 1.0) * norm;
        biquadA[6] = (1.0 - K / biquadA[1] + K * K) * norm;
        reset();
    }

    void set_param(int index, double value) override {
        if (index == 0) A = value;
    }

    void reset() override {
        gainchase = -1.0;
        chasespeed = 64.0;
        inputgain = 0.0;
        block_pos = 0;
        for (int c = 0; c < kMaxChannels; ++c) {
            for (int x = 0; x < 4; ++x) state[c][x] = 0.0;
            fpd[c] = fpd_seed(c);
        }
    }

    void process(double* const* ch, int64_t frames) override {
        for (int64_t i = 0; i < frames; ++i) {
            if (block_pos == 0) begin_virtual_block();

            // biquad lowpass (DF1), per channel
            for (int c = 0; c < channels_; ++c) {
                double inputSample = ch[c][i];
                if (std::fabs(inputSample) < 1.18e-23) inputSample = fpd[c] * 1.18e-17;
                double* s = state[c];  // x1, x2, y1, y2
                const double outSample = biquadA[2] * inputSample + biquadA[3] * s[0] + biquadA[4] * s[1]
                                         - biquadA[5] * s[2] - biquadA[6] * s[3];
                s[1] = s[0];
                s[0] = inputSample;
                s[3] = s[2];
                s[2] = outSample;
                ch[c][i] = outSample;
            }

            chasespeed *= 0.9999;
            chasespeed -= 0.01;
            if (chasespeed < 64.0) chasespeed = 64.0;
            // we have our chase speed compensated for recent fader activity
            gainchase = (((gainchase * chasespeed) + inputgain) / (chasespeed + 1.0));
            // gainchase is chasing the target, as a simple multiply gain factor

            for (int c = 0; c < channels_; ++c) {
                double inputSample = ch[c][i];
                if (1.0 != gainchase) inputSample *= std::pow(gainchase, 3);
                // this trim control cuts back extra hard because we will amplify after the distortion
                // that will shift the distortion/antidistortion curve, in order to make faded settings
                // slightly 'expanded' and fall back in the soundstage, subtly

                if (inputSample > 1.097) inputSample = 1.097;
                if (inputSample < -1.097) inputSample = -1.097;
                inputSample = ((std::sin(inputSample * std::fabs(inputSample)) /
                                ((std::fabs(inputSample) == 0.0) ? 1 : std::fabs(inputSample))) * 0.8) +
                              (std::sin(inputSample) * 0.2);
                // this is a version of Spiral blended 80/20 with regular Density ConsoleChannel.
                // It's blending between two different harmonics in the overtones of the algorithm

                if (1.0 != gainchase && 0.0 != gainchase) inputSample /= gainchase;
                // we re-amplify after the distortion relative to how much we cut back previously.

                fpd_advance(fpd[c]);  // original dither block: state advance only
                ch[c][i] = inputSample;
            }

            if (++block_pos == kVirtualBlock) block_pos = 0;
        }
    }

private:
    // Per-host-block setup of the original, run every kVirtualBlock frames.
    void begin_virtual_block() {
        inputgain = A * 1.272019649514069;
        // which is, in fact, the square root of 1.618033988749894848204586...
        // Neutral gain through the whole system with a full scale sine is 0.772 on the gain knob
        if (gainchase != inputgain) chasespeed *= 2.0;
        if (chasespeed > kVirtualBlock) chasespeed = kVirtualBlock;
        if (gainchase < 0.0) gainchase = inputgain;
    }

    double A = 0.772;
    double inputgain = 0.0;
    double gainchase = -1.0;
    double chasespeed = 64.0;
    int block_pos = 0;
    double biquadA[7];
    double state[kMaxChannels][4];
    uint32_t fpd[kMaxChannels];
};

Processor* create(double sr, int ch) { return new Console7Channel(sr, ch); }

}  // namespace

extern const ProcessorSpec kConsole7ChannelSpec = {
    "aw.console7_channel",
    "saturator",
    "console_channel",
    "Console7Channel (Airwindows)",
    "Encode half of the Console7 summing pair: 20 kHz lowpass, fader, Spiral/Density-style sine saturation.",
    {"airwindows", "Console7Channel", "MIT", "Console7ChannelProc.cpp, Console7Channel.cpp, Console7Channel.h"},
    kParams,
    static_cast<int>(sizeof(kParams) / sizeof(kParams[0])),
    true,
    0,
    &create,
};

}  // namespace mmx
