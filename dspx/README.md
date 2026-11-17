# DSP extensions

`dspx` holds additive reference DSP processors and shared building blocks. The
original processor definitions and DSP implementations remain in `dsp`.

## Layout and registration

| Module | Responsibility |
|---|---|
| `registry.py` | Discover `procs/*.py` in filename order, reject duplicate or undeclared registrations, and return isolated definition copies. |
| `params.py` | Parameter declaration helpers compatible with the original processor schema, without importing the processor registry. |
| `contracts.py` | Extend parameter validation and JSON Schema for curves and assets; invoke type-specific relationship checks after ordinary validation and default resolution. |
| `assets.py` | Register asset resolvers and validate asset identifiers. |
| `chain.py` | Expand composites and implement optional stereo, mid, side, left and right channel targeting, including prohibited-type checks. |
| `bb/` | Reusable building blocks for crossovers, dynamics, FIR design/convolution, delay lines, curves and pitch analysis. |
| `procs/` | One module per processor type, with declarations and reference implementations. |

Processor modules expose `SPECS` (definition list) and `IMPLS` (type-to-function
mapping). Optional declarations are `TIME_VARYING`, `COMPOSITES`, `RESOLVE_PARAMS`,
`SCHEMA_PATCH` and `CROSS_VALIDATE`. The latter three map type names to functions.
A parameter resolver accepts raw params (including `None`) before scalar defaults
and returns a fresh dictionary, preserving explicitly supplied values. A schema
patch receives its type's params schema and modifies it in place. Hooks are
collected with duplicate, undeclared-type and callable checks; contract code
does not dispatch on processor names. Composite functions accept resolved parameters and return a
nonempty list of non-composite chain items. A cross-validator accepts a resolved
parameter dictionary, raises `ParamError` for invalid relationships, and returns
no result. Validators must not modify parameters or import `dsp.processors` at
module load time. Checks requiring audio or a sample rate remain in the processor.

Implementations accept `fn(x, sr, params, *, seed)` and return `(y, sr, stats)`;
audio uses float64 arrays shaped `(frames, channels)`. FFT calls explicitly use
`workers=1`, and random generators use PCG64. Existing types without a declared
cross-validator retain their original parameter validation behavior.

The delay cross-validators check tempo conversion, array relationships and the
feedback/time combination before rendering. `bb.delayline.feedback_limit`
computes a conservative 60-second decay bound using the longest feedback line,
the final one-second CT-8 measurement window, bounded stored feedback state, and
the sum of multitap gains. Loop-filter attenuation is never credited.

## Dependency public APIs

These modules call already installed dependencies; no source code from these
packages is vendored here and no new package is introduced. Observed versions
recorded by W1 are NumPy 2.5.3, SciPy 1.18.1 and librosa 1.0.0.

| Dependency | License | Public API use |
|---|---|---|
| SciPy | BSD-3-Clause | Butterworth, Bessel and elliptic filter design; analog frequency transformations, bilinear transformations and SOS APIs in `cut_filter.py` and `tilt_eq.py`; `signal.butter`, `iirnotch`, `sosfilt`, `sosfiltfilt`, `resample_poly`; single-worker FFT APIs including `fft.rfft`, `rfftfreq`, `next_fast_len`; `optimize.minimize_scalar` in `dc_remove.py` and `dehum.py`. |
| librosa | ISC | Lazy calls to public `yin` and `pyin` in `bb/pitch.py`; fixed-grid conversion and YIN voicing checks are local code. |
| NumPy | BSD-3-Clause | Float64 arrays, vectorized arithmetic, indexing, interpolation, Kaiser windows, linear algebra, and deterministic `random.Generator` / `random.PCG64`. |

Sources and licenses:

- SciPy [source, v1.18.1](https://github.com/scipy/scipy/tree/v1.18.1) and
  [license](https://github.com/scipy/scipy/blob/v1.18.1/LICENSE.txt).
- librosa [source, 1.0.0](https://github.com/librosa/librosa/tree/1.0.0) and
  [license](https://github.com/librosa/librosa/blob/1.0.0/LICENSE.md).
- NumPy [source](https://github.com/numpy/numpy) and
  [license](https://github.com/numpy/numpy/blob/main/LICENSE.txt).

Frequency sampling, cepstral folding and partitioned convolution in `bb/fir.py`
are independently implemented using public FFT APIs and NumPy's Kaiser window.
The curve evaluator and time-varying notch are independently expressed from
their mathematical definitions. The curve evaluator follows the secant/tangent
and circle limiter construction described by Fritsch & Carlson, “Monotone
Piecewise Cubic Interpolation”, SIAM Journal on Numerical Analysis (1980).
No external implementation was consulted or copied for those algorithms.

This document consolidates the former W1b and W1d API notes. `third_party/` is
reserved for imported third-party code and its required provenance and licenses.

## Reverb core (bb/reverb.py) sources


No external implementation source was copied or adapted. Existing NumPy and
SciPy public APIs are used, with no new dependencies. SciPy 1.18.1 is under
BSD-3-Clause; its existing distribution supplies its license. The code calls
`scipy.signal.lfilter`, `sosfilt`, `butter` and the repository's BB-07 FFT
convolution and BB-09 delay line. All FFT calls in BB-07 use `workers=1`.

Formula references read for this unit:

- J. O. Smith, *Physical Audio Signal Processing*, Artificial Reverberation:
  https://www.dsprelated.com/freebooks/pasp/Artificial_Reverberation.html
- Välimäki et al., *Fifty Years of Artificial Reverberation*, IEEE TASLP,
  20(5), 2012: https://research.aalto.fi/en/publications/fifty-years-of-artificial-reverberation/
- Välimäki et al., *Late Reverberation Synthesis Using Filtered Velvet Noise*,
  Applied Sciences 7(5), 483 (2017): https://doi.org/10.3390/app7050483

FDN decay uses `g_i = exp(-ln(1000) D_i / (sr T60))`. Orthogonal mixing is a
normalised Sylvester matrix. Allpass recurrences and random pulse cells are
independently expressed. No product output, firmware or GPL/AGPL source was
consulted.

## Time and creative building blocks (W2g) sources


No third-party implementation source was copied or translated. Existing
NumPy and SciPy 1.18.1 (BSD-3-Clause) public APIs provide iirpeak, butter,
lfilter, sosfilt, fftconvolve and the FFT analysis used in acceptance tests.
FIR design, fractional reads, envelopes, crossovers and note conversion reuse
the repository's BB-02/03/05/07/09 APIs.

The TPT state equations are independently derived by solving two trapezoidal
integrators in a state-variable feedback loop. The parameter conversion solves
the analog lowpass magnitude polynomial before prewarping; it is documented
in `dspx/bb/svf.py`. The named textbook is Vadim Zavalishin, *The Art of VA
Filter Design*. Its publisher PDF URLs returned 404 during this task, so no
edition-specific equation or source-code attribution is claimed.

The channel vocoder uses the specification's four-pole filter bank,
rectification, one-pole followers, additive harmonic carrier and bank sum.
Stop/start positions are analytic integrals of power-law speed curves.
Noise colour uses frequency-sampled FIRs; shot-noise normalization follows
variance = arrival-rate/sample-rate times impulse-response energy.

API documentation:

- https://docs.scipy.org/doc/scipy/reference/generated/scipy.signal.iirpeak.html
- https://docs.scipy.org/doc/scipy/reference/generated/scipy.signal.fftconvolve.html
- https://docs.scipy.org/doc/scipy/reference/generated/scipy.signal.butter.html

## Vintage EQ and transformer (W2a2) sources


No third-party implementation was copied or vendored. Existing NumPy 2.5.3
(BSD-3-Clause) and SciPy 1.18.1 (BSD-3-Clause) are the only external APIs used.
The existing BB-13 polyphase implementation is reused unchanged.

- SciPy `signal.bilinear`, `tf2sos`, `sosfilt`, `lfilter`, `sosfreqz`, and
  `freqz`: public filter design, evaluation and filtering API.
  [SciPy signal documentation](https://docs.scipy.org/doc/scipy/reference/signal.html).
- General shelf/peak background: Välimäki and Reiss, *All About Audio
  Equalization: Solutions and Frontiers*, Applied Sciences 6(5), 129 (2016),
  sections 3 and 6.1, [paper](https://doi.org/10.3390/app6050129).
  Source code linked by that paper was not consulted.
- EQ equations are derived from normalized RC and series RLC nodal equations
  in `dspx/bb/analog_eq.py`. These are generic buffered networks; component
  ratios and control laws are chosen explicitly in that module. Historical
  circuit drawings and provisional switch frequencies have not been verified.
- Transformer equations are an independent derivation of the specification's
  leaky integration / memoryless saturation / differentiation structure.
  `dspx/bb/nonlinear.py:transformer_flux` documents the ODE, chain rule and
  chosen constants. The specified transformer paper's full text was not
  available; none of its equations or implementation code is claimed here.

## Adaptive limiter (W3d) sources


No external implementation code was copied or ported. No dependency was added.
The added BB-03 helpers use the existing SciPy 1.18.1 public API
(`scipy.ndimage.minimum_filter1d`, `convolve1d`; BSD-3-Clause), and NumPy.
The processor reuses the repository's `dsp/reference/truepeak.py` without
changing its interpolator, detector or measurement functions.

Algorithm literature used for independent implementation and selection:

- Hämäläinen, DAFx-02, sections 3.2–3.4: order-statistics control and averaging.
  [Author's paper](https://users.aalto.fi/~hamalap5/dafx2002/dafx_hamalainen.pdf).
  The implementation uses a minimum filter on gain and a nonnegative Hann
  average. It does not port the paper's implementation.
- Giannoulis, Massberg, Reiss, JAES 60(6), 2012, section 2.3: single and
  dual release networks, and decoupled peak release.
  [Paper](https://www.eecs.qmul.ac.uk/~josh/documents/2012/GiannoulisMassbergReiss-dynamicrangecompression-JAES2012.pdf).
- Giannoulis, Massberg, Reiss, JAES 61(10), 2013, sections 2.1.2–2.1.4:
  crest-based automation (equation 8) and spectral-flux-based automation.
  [Paper](https://www.eecs.qmul.ac.uk/~josh/documents/2013/Giannoulis%20Massberg%20Reiss%20-%20dynamic%20range%20compression%20automation%20-%20JAES%202013.pdf).

The duty/crest combination, 100 ms history, duty/crest scale factors 3/4,
20 ms adaptive hold and transient allocation in `AdaptiveReleaseState`
are explicit local design choices from the task specification, not claimed
as an exact published release formula. Spectral flux was not selected:
the requested release control depends on GR duration and crest and needs
no additional STFT frame clock. The fixed-release comparator uses zero
adaptive hold and the stated exponential release time constant.
