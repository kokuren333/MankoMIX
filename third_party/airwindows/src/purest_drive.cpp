// purest_drive.cpp -- Airwindows PurestDrive ported to the MankoMIX native core.
//
// SPDX-License-Identifier: MIT
// Original work: PurestDrive by Chris Johnson (airwindows).
//   Copyright (c) 2016 airwindows, Airwindows uses the MIT license.
//   https://github.com/airwindows/airwindows
//   commit 94cb6793893027fb418ffac7cdbfcb9b4c82aadb
//   plugins/LinuxVST/src/PurestDrive/PurestDriveProc.cpp (processDoubleReplacing)
//   plugins/LinuxVST/src/PurestDrive/PurestDrive.cpp, PurestDrive.h
// License text: third_party/airwindows/LICENSE. Origin: third_party/airwindows/ORIGIN.md.
//
// Changes for MankoMIX (the per-sample algorithm is unchanged):
//   - VST shell removed (AudioEffectX, programs, chunks, display strings).
//   - Stereo L/R code generalized to N independent channels.
//   - fpd state seeded with fixed constants (mmx::fpd_seed) instead of rand().
//     It is only used by the original denormal guard; the 64-bit dither line
//     was already commented out in the original double path, so no noise is
//     added to the signal.
//   - Parameter A exposed as "drive" (0..1, same scale as the original knob).
#include <cmath>

#include "mmx_processor.h"

namespace mmx {
namespace {

const ParamSpec kParams[] = {
    {"drive", "norm", 0.0, 1.0, 0.0,
     "Saturation intensity (original 'Drive' knob). 0 = transparent."},
};

class PurestDrive final : public Processor {
public:
    PurestDrive(double sr, int ch) : Processor(sr, ch) { reset(); }

    void set_param(int index, double value) override {
        if (index == 0) A = value;
    }

    void reset() override {
        for (int c = 0; c < kMaxChannels; ++c) {
            previousSample[c] = 0.0;
            fpd[c] = fpd_seed(c);
        }
    }

    void process(double* const* ch, int64_t frames) override {
        const double intensity = A;
        for (int c = 0; c < channels_; ++c) {
            double* buf = ch[c];
            double prev = previousSample[c];
            uint32_t f = fpd[c];
            for (int64_t i = 0; i < frames; ++i) {
                double inputSample = buf[i];
                if (std::fabs(inputSample) < 1.18e-23) inputSample = f * 1.18e-17;
                const double drySample = inputSample;

                inputSample = std::sin(inputSample);
                // basic distortion factor
                const double apply = (std::fabs(prev + inputSample) / 2.0) * intensity;
                // saturate less if previous sample was undistorted and low level, or if it was
                // inverse polarity. Lets through highs and brightness more.
                inputSample = (drySample * (1.0 - apply)) + (inputSample * apply);
                // dry-wet control for intensity also has FM modulation to clean up highs
                prev = std::sin(drySample);
                // apply the sine while storing previous sample

                fpd_advance(f);  // original dither block: state advance only
                buf[i] = inputSample;
            }
            previousSample[c] = prev;
            fpd[c] = f;
        }
    }

private:
    double A = 0.0;
    double previousSample[kMaxChannels];
    uint32_t fpd[kMaxChannels];
};

Processor* create(double sr, int ch) { return new PurestDrive(sr, ch); }

}  // namespace

extern const ProcessorSpec kPurestDriveSpec = {
    "aw.purest_drive",
    "saturator",
    "channel_drive",
    "PurestDrive (Airwindows)",
    "Program-dependent sine saturation; saturates less on low-level or polarity-reversing material.",
    {"airwindows", "PurestDrive", "MIT", "PurestDriveProc.cpp, PurestDrive.cpp, PurestDrive.h"},
    kParams,
    static_cast<int>(sizeof(kParams) / sizeof(kParams[0])),
    true,
    0,
    &create,
};

}  // namespace mmx
