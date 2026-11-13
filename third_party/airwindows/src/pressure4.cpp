// pressure4.cpp -- Airwindows Pressure4 ported to the MankoMIX native core.
//
// SPDX-License-Identifier: MIT
// Original work: Pressure4 by Chris Johnson (airwindows).
//   Copyright (c) 2016 airwindows, Airwindows uses the MIT license.
//   https://github.com/airwindows/airwindows
//   commit 94cb6793893027fb418ffac7cdbfcb9b4c82aadb
//   plugins/LinuxVST/src/Pressure4/Pressure4Proc.cpp (processDoubleReplacing)
//   plugins/LinuxVST/src/Pressure4/Pressure4.cpp, Pressure4.h
// License text: third_party/airwindows/LICENSE. Origin: third_party/airwindows/ORIGIN.md.
//
// Changes for MankoMIX (the per-sample algorithm is unchanged):
//   - VST shell removed. The original links L and R (detector = max of both);
//     here the detector is the max over all N channels, gain applied to all.
//   - Per-block derived constants (threshold, release, mewiness ...) are
//     computed when a parameter changes instead of at each host block; they
//     depend only on parameters and sample rate, so the result is identical.
//   - Parameter C ("Mewiness", stored 0..1 and displayed as C*2-1) is exposed
//     in its displayed range -1..1 as "mewiness"; D as linear "output_gain".
//   - fpd seeded with fixed constants; used only by the denormal guard.
//   - `flip` is never toggled in the original double path, so only the "B"
//     coefficient set is used; both branches are kept verbatim.
#include <cmath>

#include "mmx_processor.h"

namespace mmx {
namespace {

const ParamSpec kParams[] = {
    {"pressure", "norm", 0.0, 1.0, 0.0,
     "Compression amount (original 'Pressure'); threshold = 1 - 0.95 * pressure with matching makeup."},
    {"speed", "norm", 0.0, 1.0, 0.2, "Release speed (original 'Speed')."},
    {"mewiness", "bipolar", -1.0, 1.0, 1.0,
     "Vari-mu curvature (original 'Mewiness'): +1 squares the gain coefficient, -1 takes its root."},
    {"output_gain", "linear", 0.0, 1.0, 1.0, "Output gain before the final sine overdrive stage."},
};

class Pressure4 final : public Processor {
public:
    Pressure4(double sr, int ch) : Processor(sr, ch) {
        update();
        reset();
    }

    void set_param(int index, double value) override {
        switch (index) {
            case 0: A = value; break;
            case 1: B = value; break;
            case 2: C = (value + 1.0) / 2.0; break;
            case 3: D = value; break;
            default: break;
        }
        update();
    }

    void reset() override {
        muSpeedA = 10000;
        muSpeedB = 10000;
        muCoefficientA = 1;
        muCoefficientB = 1;
        muVary = 1;
        muAttack = 0;
        muNewSpeed = 0;
        flip = false;
        for (int c = 0; c < kMaxChannels; ++c) fpd[c] = fpd_seed(c);
    }

    void process(double* const* ch, int64_t frames) override {
        double sample[kMaxChannels];
        for (int64_t i = 0; i < frames; ++i) {
            double inputSense = 0.0;
            for (int c = 0; c < channels_; ++c) {
                double inputSample = ch[c][i];
                if (std::fabs(inputSample) < 1.18e-23) inputSample = fpd[c] * 1.18e-17;
                inputSample = inputSample * muMakeupGain;
                sample[c] = inputSample;
                // we will take the greater of all channels and just use that, then apply the
                // result to all channels.
                if (c == 0 || std::fabs(inputSample) > inputSense) inputSense = std::fabs(inputSample);
            }

            if (flip) {
                if (inputSense > threshold) {
                    muVary = threshold / inputSense;
                    muAttack = std::sqrt(std::fabs(muSpeedA));
                    muCoefficientA = muCoefficientA * (muAttack - 1.0);
                    if (muVary < threshold) muCoefficientA = muCoefficientA + threshold;
                    else muCoefficientA = muCoefficientA + muVary;
                    muCoefficientA = muCoefficientA / muAttack;
                } else {
                    muCoefficientA = muCoefficientA * ((muSpeedA * muSpeedA) - 1.0);
                    muCoefficientA = muCoefficientA + 1.0;
                    muCoefficientA = muCoefficientA / (muSpeedA * muSpeedA);
                }
                muNewSpeed = muSpeedA * (muSpeedA - 1);
                muNewSpeed = muNewSpeed + std::fabs(inputSense * release) + fastest;
                muSpeedA = muNewSpeed / muSpeedA;
            } else {
                if (inputSense > threshold) {
                    muVary = threshold / inputSense;
                    muAttack = std::sqrt(std::fabs(muSpeedB));
                    muCoefficientB = muCoefficientB * (muAttack - 1);
                    if (muVary < threshold) muCoefficientB = muCoefficientB + threshold;
                    else muCoefficientB = muCoefficientB + muVary;
                    muCoefficientB = muCoefficientB / muAttack;
                } else {
                    muCoefficientB = muCoefficientB * ((muSpeedB * muSpeedB) - 1.0);
                    muCoefficientB = muCoefficientB + 1.0;
                    muCoefficientB = muCoefficientB / (muSpeedB * muSpeedB);
                }
                muNewSpeed = muSpeedB * (muSpeedB - 1);
                muNewSpeed = muNewSpeed + std::fabs(inputSense * release) + fastest;
                muSpeedB = muNewSpeed / muSpeedB;
            }
            // got coefficients, adjusted speeds

            double coefficient;
            if (flip) {
                if (positivemu) coefficient = std::pow(muCoefficientA, 2);
                else coefficient = std::sqrt(muCoefficientA);
                coefficient = (coefficient * mewiness) + (muCoefficientA * unmewiness);
            } else {
                if (positivemu) coefficient = std::pow(muCoefficientB, 2);
                else coefficient = std::sqrt(muCoefficientB);
                coefficient = (coefficient * mewiness) + (muCoefficientB * unmewiness);
            }
            // applied compression with vari-vari-mu

            for (int c = 0; c < channels_; ++c) {
                double inputSample = sample[c] * coefficient;
                if (outputGain != 1.0) inputSample *= outputGain;

                double bridgerectifier = std::fabs(inputSample);
                if (bridgerectifier > 1.57079633) bridgerectifier = 1.0;
                else bridgerectifier = std::sin(bridgerectifier);
                if (inputSample > 0) inputSample = bridgerectifier;
                else inputSample = -bridgerectifier;
                // second stage of overdrive to prevent overs and allow bloody loud extremeness

                fpd_advance(fpd[c]);  // original dither block: state advance only
                ch[c][i] = inputSample;
            }
        }
    }

private:
    // Per-block constants of the original processDoubleReplacing.
    void update() {
        double overallscale = 1.0;
        overallscale /= 44100.0;
        overallscale *= sample_rate_;
        threshold = 1.0 - (A * 0.95);
        muMakeupGain = 1.0 / threshold;
        // gain settings around threshold
        release = std::pow((1.28 - B), 5) * 32768.0;
        release /= overallscale;
        fastest = std::sqrt(release);
        // speed settings around release
        mewiness = (C * 2.0) - 1.0;
        outputGain = D;
        if (mewiness >= 0) {
            positivemu = true;
            unmewiness = 1.0 - mewiness;
        } else {
            positivemu = false;
            mewiness = -mewiness;
            unmewiness = 1.0 - mewiness;
        }
    }

    // parameters (original 0..1 storage)
    double A = 0.0;
    double B = 0.2;
    double C = 1.0;
    double D = 1.0;
    // derived per-block constants
    double threshold = 1.0, muMakeupGain = 1.0, release = 0.0, fastest = 0.0;
    double mewiness = 1.0, unmewiness = 0.0, outputGain = 1.0;
    bool positivemu = true;
    // signal state
    double muVary = 1, muAttack = 0, muNewSpeed = 0;
    double muSpeedA = 10000, muSpeedB = 10000;
    double muCoefficientA = 1, muCoefficientB = 1;
    bool flip = false;
    uint32_t fpd[kMaxChannels];
};

Processor* create(double sr, int ch) { return new Pressure4(sr, ch); }

}  // namespace

extern const ProcessorSpec kPressure4Spec = {
    "aw.pressure4",
    "compressor",
    "vari_mu_bus",
    "Pressure4 (Airwindows)",
    "Stereo-linked vari-mu style compressor with a final sine overdrive stage; gentle bus glue at low pressure.",
    {"airwindows", "Pressure4", "MIT", "Pressure4Proc.cpp, Pressure4.cpp, Pressure4.h"},
    kParams,
    static_cast<int>(sizeof(kParams) / sizeof(kParams[0])),
    true,
    0,
    &create,
};

}  // namespace mmx
