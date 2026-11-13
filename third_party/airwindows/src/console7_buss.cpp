// console7_buss.cpp -- Airwindows Console7Buss ported to the MankoMIX native core.
//
// SPDX-License-Identifier: MIT
// Original work: Console7Buss by Chris Johnson (airwindows).
//   Copyright (c) 2016 airwindows, Airwindows uses the MIT license.
//   https://github.com/airwindows/airwindows
//   commit 94cb6793893027fb418ffac7cdbfcb9b4c82aadb
//   plugins/LinuxVST/src/Console7Buss/Console7BussProc.cpp (processDoubleReplacing)
//   plugins/LinuxVST/src/Console7Buss/Console7Buss.cpp, Console7Buss.h
// License text: third_party/airwindows/LICENSE. Origin: third_party/airwindows/ORIGIN.md.
//
// Console7Buss is the decode half of the Console7 summing pair (asin-based
// "anti-saturation" after the sum of Console7Channel outputs).
//
// Changes for MankoMIX (the per-sample algorithm is unchanged):
//   - VST shell removed; stereo L/R code generalized to N channels.
//   - Fader-chase setup runs on a fixed virtual host block of 512 frames
//     (block-size independence; see console7_channel.cpp).
//   - 20 kHz lowpass frequency ratio clamped to 0.49 of the sample rate.
//   - fpd seeded with fixed constants; used only by the denormal guard.
#include <cmath>

#include "mmx_processor.h"

namespace mmx {
namespace {

constexpr double kPi = 3.14159265358979323846;
constexpr int kVirtualBlock = 512;

const ParamSpec kParams[] = {
    {"master", "norm", 0.0, 1.0, 1.0, "Buss master fader (original knob). 1.0 = original default."},
};

void lowpass(double* q, double freq, double reso) {
    q[0] = freq;
    q[1] = reso;
    const double K = std::tan(kPi * q[0]);
    const double norm = 1.0 / (1.0 + K / q[1] + K * K);
    q[2] = K * K * norm;
    q[3] = 2.0 * q[2];
    q[4] = q[2];
    q[5] = 2.0 * (K * K - 1.0) * norm;
    q[6] = (1.0 - K / q[1] + K * K) * norm;
}

inline double df1(const double* q, double* s, double x) {
    const double y = q[2] * x + q[3] * s[0] + q[4] * s[1] - q[5] * s[2] - q[6] * s[3];
    s[1] = s[0];
    s[0] = x;
    s[3] = s[2];
    s[2] = y;
    return y;
}

class Console7Buss final : public Processor {
public:
    Console7Buss(double sr, int ch) : Processor(sr, ch) {
        double freq = 20000.0 / sample_rate_;
        if (freq > 0.49) freq = 0.49;
        lowpass(biquadA, freq, 0.618033988749894848204586);
        lowpass(biquadB, freq, 0.5);
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
            for (int x = 0; x < 4; ++x) {
                stateA[c][x] = 0.0;
                stateB[c][x] = 0.0;
            }
            fpd[c] = fpd_seed(c);
        }
    }

    void process(double* const* ch, int64_t frames) override {
        for (int64_t i = 0; i < frames; ++i) {
            if (block_pos == 0) begin_virtual_block();

            for (int c = 0; c < channels_; ++c) {
                double inputSample = ch[c][i];
                if (std::fabs(inputSample) < 1.18e-23) inputSample = fpd[c] * 1.18e-17;
                ch[c][i] = df1(biquadA, stateA[c], inputSample);
            }

            chasespeed *= 0.9999;
            chasespeed -= 0.01;
            if (chasespeed < 64.0) chasespeed = 64.0;
            // we have our chase speed compensated for recent fader activity
            gainchase = (((gainchase * chasespeed) + inputgain) / (chasespeed + 1.0));
            // gainchase is chasing the target, as a simple multiply gain factor

            for (int c = 0; c < channels_; ++c) {
                double inputSample = ch[c][i];
                if (1.0 != gainchase) inputSample *= std::sqrt(gainchase);
                // done with trim control

                if (inputSample > 1.0) inputSample = 1.0;
                if (inputSample < -1.0) inputSample = -1.0;
                inputSample = ((std::asin(inputSample * std::fabs(inputSample)) /
                                ((std::fabs(inputSample) == 0.0) ? 1 : std::fabs(inputSample))) *
                               0.618033988749894848204586) +
                              (std::asin(inputSample) * 0.381966011250105);
                // this is an asin version of Spiral blended with regular asin ConsoleBuss.

                inputSample = df1(biquadB, stateB[c], inputSample);

                if (1.0 != gainchase) inputSample *= std::sqrt(gainchase);

                fpd_advance(fpd[c]);  // original dither block: state advance only
                ch[c][i] = inputSample;
            }

            if (++block_pos == kVirtualBlock) block_pos = 0;
        }
    }

private:
    void begin_virtual_block() {
        inputgain = A * 1.03;
        if (gainchase != inputgain) chasespeed *= 2.0;
        if (chasespeed > kVirtualBlock) chasespeed = kVirtualBlock;
        if (gainchase < 0.0) gainchase = inputgain;
    }

    double A = 1.0;
    double inputgain = 0.0;
    double gainchase = -1.0;
    double chasespeed = 64.0;
    int block_pos = 0;
    double biquadA[7];
    double biquadB[7];
    double stateA[kMaxChannels][4];
    double stateB[kMaxChannels][4];
    uint32_t fpd[kMaxChannels];
};

Processor* create(double sr, int ch) { return new Console7Buss(sr, ch); }

}  // namespace

extern const ProcessorSpec kConsole7BussSpec = {
    "aw.console7_buss",
    "saturator",
    "console_buss",
    "Console7Buss (Airwindows)",
    "Decode half of the Console7 summing pair: asin-based buss stage with 20 kHz lowpass filters.",
    {"airwindows", "Console7Buss", "MIT", "Console7BussProc.cpp, Console7Buss.cpp, Console7Buss.h"},
    kParams,
    static_cast<int>(sizeof(kParams) / sizeof(kParams[0])),
    true,
    0,
    &create,
};

}  // namespace mmx
