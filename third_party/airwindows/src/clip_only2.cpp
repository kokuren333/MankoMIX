// clip_only2.cpp -- Airwindows ClipOnly2 ported to the MankoMIX native core.
//
// SPDX-License-Identifier: MIT
// Original work: ClipOnly2 by Chris Johnson (airwindows).
//   Copyright (c) 2016 airwindows, Airwindows uses the MIT license.
//   https://github.com/airwindows/airwindows
//   commit 94cb6793893027fb418ffac7cdbfcb9b4c82aadb
//   plugins/LinuxVST/src/ClipOnly2/ClipOnly2Proc.cpp (processDoubleReplacing)
//   plugins/LinuxVST/src/ClipOnly2/ClipOnly2.cpp, ClipOnly2.h
// License text: third_party/airwindows/LICENSE. Origin: third_party/airwindows/ORIGIN.md.
//
// Changes for MankoMIX (the per-sample clipping algorithm is unchanged):
//   - VST shell removed; stereo L/R code generalized to N independent channels.
//   - Gain staging around the original algorithm: the signal is multiplied by
//     input_gain * (refclip / ceiling) before and by (ceiling / refclip) after
//     the clipper, where refclip = 0.9549925859 (= -0.4 dBFS) is the fixed
//     clip point of the original. At the defaults (input_gain_db = 0,
//     ceiling_db = -0.4) both factors are exactly 1.0, i.e. the original.
//   - intermediate[] sized 17 instead of 16: the original writes
//     intermediate[spacing] with spacing up to 16 (only reachable at >= 705.6 kHz).
//   - ClipOnly2 has no fpd/dither state (the original leaves it off).
// Latency: one sample at every sample rate. The original's shift loop copies
// the newest value through the whole buffer, so the effective delay is one
// sample regardless of `spacing`.
#include <cmath>

#include "mmx_processor.h"

namespace mmx {
namespace {

constexpr double kRefClip = 0.9549925859;      // original fixed clip point (-0.4 dBFS)
constexpr double kRefClipDb = -0.4;

const ParamSpec kParams[] = {
    {"input_gain_db", "dB", -24.0, 24.0, 0.0, "Drive into the clipper."},
    {"ceiling_db", "dBFS", -24.0, 0.0, kRefClipDb,
     "Clip ceiling. Output stays at or below this level (-0.4 = original ClipOnly2)."},
};

class ClipOnly2 final : public Processor {
public:
    ClipOnly2(double sr, int ch) : Processor(sr, ch) {
        double overallscale = 1.0;
        overallscale /= 44100.0;
        overallscale *= sample_rate_;
        spacing = static_cast<int>(std::floor(overallscale));  // usually 1, 2 or 4
        if (spacing < 1) spacing = 1;
        if (spacing > 16) spacing = 16;
        update_gains();
        reset();
    }

    void set_param(int index, double value) override {
        if (index == 0) input_gain_db = value;
        if (index == 1) ceiling_db = value;
        update_gains();
    }

    void reset() override {
        for (int c = 0; c < kMaxChannels; ++c) {
            lastSample[c] = 0.0;
            wasPosClip[c] = false;
            wasNegClip[c] = false;
            for (int x = 0; x < 17; ++x) intermediate[c][x] = 0.0;
        }
    }

    int latency() const override { return 1; }

    void process(double* const* ch, int64_t frames) override {
        for (int c = 0; c < channels_; ++c) {
            double* buf = ch[c];
            double* inter = intermediate[c];
            for (int64_t i = 0; i < frames; ++i) {
                double inputSample = buf[i];
                if (pre_gain != 1.0) inputSample *= pre_gain;

                // begin ClipOnly2 as a little, compressed chunk that can be dropped into code
                if (inputSample > 4.0) inputSample = 4.0;
                if (inputSample < -4.0) inputSample = -4.0;
                if (wasPosClip[c] == true) {  // current will be over
                    if (inputSample < lastSample[c]) lastSample[c] = 0.7058208 + (inputSample * 0.2609148);
                    else lastSample[c] = 0.2491717 + (lastSample[c] * 0.7390851);
                }
                wasPosClip[c] = false;
                if (inputSample > 0.9549925859) {
                    wasPosClip[c] = true;
                    inputSample = 0.7058208 + (lastSample[c] * 0.2609148);
                }
                if (wasNegClip[c] == true) {  // current will be -over
                    if (inputSample > lastSample[c]) lastSample[c] = -0.7058208 + (inputSample * 0.2609148);
                    else lastSample[c] = -0.2491717 + (lastSample[c] * 0.7390851);
                }
                wasNegClip[c] = false;
                if (inputSample < -0.9549925859) {
                    wasNegClip[c] = true;
                    inputSample = -0.7058208 + (lastSample[c] * 0.2609148);
                }
                inter[spacing] = inputSample;
                inputSample = lastSample[c];  // latency is however many samples equals one 44.1k sample
                for (int x = spacing; x > 0; x--) inter[x - 1] = inter[x];
                lastSample[c] = inter[0];  // run a little buffer to handle this
                // end ClipOnly2 chunk

                if (post_gain != 1.0) inputSample *= post_gain;
                buf[i] = inputSample;
            }
        }
    }

private:
    void update_gains() {
        const double ceiling = std::pow(10.0, ceiling_db / 20.0);
        double scale = ceiling / kRefClip;
        if (std::fabs(scale - 1.0) < 1e-9) scale = 1.0;  // default: exact original
        post_gain = scale;
        pre_gain = std::pow(10.0, input_gain_db / 20.0) / scale;
        if (std::fabs(pre_gain - 1.0) < 1e-12) pre_gain = 1.0;
    }

    double input_gain_db = 0.0;
    double ceiling_db = kRefClipDb;
    double pre_gain = 1.0;
    double post_gain = 1.0;
    int spacing = 1;
    double lastSample[kMaxChannels];
    double intermediate[kMaxChannels][17];
    bool wasPosClip[kMaxChannels];
    bool wasNegClip[kMaxChannels];
};

Processor* create(double sr, int ch) { return new ClipOnly2(sr, ch); }

}  // namespace

extern const ProcessorSpec kClipOnly2Spec = {
    "aw.clip_only2",
    "clipper",
    "safety_clipper",
    "ClipOnly2 (Airwindows)",
    "Soft-knee safety clipper with one sample of lookahead-like latency; transparent below the ceiling.",
    {"airwindows", "ClipOnly2", "MIT", "ClipOnly2Proc.cpp, ClipOnly2.cpp, ClipOnly2.h"},
    kParams,
    static_cast<int>(sizeof(kParams) / sizeof(kParams[0])),
    true,
    1,
    &create,
};

}  // namespace mmx
