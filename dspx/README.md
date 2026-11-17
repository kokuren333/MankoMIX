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


## BB-16 offline model runtime

`bb/ml.py` adds kinds `denoise`, `amp_capture`, `separate` above the existing
core model catalogue and local BYOW registrations. Legacy `task=separation`
resolves as `separate`. The core catalogue/defaults and separation workers keep
their existing contracts. No weights are bundled.

- `model_entry(id, kind=None)` reads metadata only. The `models` asset resolver
  uses it; validation never downloads or imports ONNX Runtime.
- `pull(id)` is an explicit user operation delegating to
  `core.registry.model_pull`; the existing `model pull` CLI also works.
- `resolve_for_run(id, kind=None)` re-hashes every local file without a cached
  verification shortcut, checks pinned size and returns core's resolved paths.
  A missing file/runtime raises `ModelUnavailable`; unknown IDs, wrong kinds,
  corrupt weights and malformed inference graphs are errors, never fallback.
- `session(bytes_or_path)` uses CPU only, sequential execution, intra/inter
  threads 1, disabled graph optimization and deterministic compute. Sessions
  are created per render. No environment variable can select a GPU provider.
- `infer(x, sr, resolved)` returns same-length float64 audio and model ID/hash,
  runtime/code versions, actual provider, chunk geometry, license and caveats.
  Use `(frames, channels)` input. `infer_blocks(blocks, sr, resolved)` is an
  **offline context replay** convenience; it concatenates caller blocks before
  inference. It does not promise independent streaming/excerpt processing.
- `waveform(x, session, chunk_samples=N, overlap_samples=O)` is a reusable
  one-input/one-output `[1,1,N]` float32 ONNX adapter. Geometry comes from the
  caller's pinned registration. Each channel runs independently; sine-squared
  normalized overlap-add and zero padding are fixed. Stateful/multi-input
  capture formats require their own adapter; this function does not guess them.
- `report_records(render_records)` extracts actual model/fallback measurements
  from engine steps or nested mix manifests, and returns `[]` for legacy input.
  The standard core Mix Report has no model-processor extension hook yet; its
  owner must connect this helper before `denoise_ml` can be marked implemented.

The pinned `speech_df3_48k` catalogue entry uses official 48 kHz ONNX graphs
from revision `7b14b895fe7fc42cab72b4a4c1e49c982bd6404b` of
[DeepFilterNet](https://github.com/Rikorose/DeepFilterNet), MIT OR Apache-2.0.
The author's README explicitly grants that license to code **and weights**.
The optional runtime is pinned to ONNX Runtime 1.30.0 in that entry. No dependency
or model package is installed by inference. Frontend, normalization and overlap
arithmetic are float64; the model ABI itself requires float32 tensors.

The adapter uses 960-sample Vorbis windows, 480-sample hops, two-frame feature
lookahead and 256-frame model chunks with 128-frame overlap, 100 past frames of
recurrent warmup, zero padding and normalized sine-squared overlap-add. Chunk
origins are anchored at clip zero. Independent channels and recurrent resets
can affect stereo image and chunk-local quality; this is recorded, not claimed
to reproduce the upstream streaming implementation. Resampling uses the existing
`dsp.reference.export.resample_poly_hq` in both directions and trims to the
original length. The compensated analysis/synthesis alignment is zero samples.

`procs/denoise_ml.py` declares the required model asset, reduction 0..60 dB
(default 18), `fallback=denoise|error` (default denoise), and RP controls. It is
track-only, offline-only, with the `model` backend. Zero amount/reduction bypasses
weight loading. Model correction is blended by `1-10**(-reduction_db/20)` before
RP region mixing and delta audition. The fallback calls existing `denoise` with
`profile=auto` and reduction capped at its declared maximum 40 dB. Records include
actual fallback parameters/reason, before/after meters, events and residual energy.
The public definition stays `implemented=False` pending the Mix Report hook.

All three investigated candidates (DeepFilterNet, RNNoise, DTLN) are trained on
conversational speech. Singing, instruments and mixes are unsuitable: musical
content can be removed as noise. Use only for narration, dialogue or raw vocal
recordings; this caveat is fixed in catalogue and execution records. No dedicated
clothing-rustle weights with verified redistribution rights were selected.

Model-free tests: `python -B -m pytest -q -p no:cacheprovider tests/test_tk_w5a.py`.
The real-model test runs **only** with `MANKOMIX_W5A_MODEL` pointing to the pinned
archive, copies it solely into the temporary test home and never downloads.
It checks two-render byte identity, transport boundaries 64/1024/30001, a known
input hash and synthetic noise/SNR observations. The baseline hash is for the
pinned adapter/runtime on the reference Windows CPU environment; an independently
reviewed known answer for another environment may be supplied via
`MANKOMIX_W5A_EXPECTED_HASH`. A missing variable skips the optional test.

## NAM capture adapter (W5b)

`bb/nam.py` uses BB-16 (`bb/ml.py`) for model lookup, BYOW settings, local
SHA-256/size verification and report-record extraction. It implements mono
classic NAM JSON versions 0.5.1/0.5.2/0.5.3: WaveNet layer arrays (dilated
causal convolutions, Tanh/ReLU/Sigmoid, optional sigmoid gate and output head)
and stacked LSTM (IFGO gates, serialized initial hidden/cell states). Multiple
audio channels run independent copies of the mono capture. Newer NAM versions,
parametric/multichannel networks, FiLM, slimmable/grouped networks and other
architectures are explicit errors. A missing/invalid sample rate is an error.

Inference is independently written numpy float64, without training, PyTorch,
ONNX conversion or a new dependency. Matrix-vector products use fixed numpy
reductions rather than threaded BLAS. The model retains state across fixed
1024-sample internal chunks, with no overlap/window. WaveNet raw-input padding
is receptive-field minus one zero samples; deeper biased layers process this
padding too. LSTM starts at its exported h0/c0 without extra prewarm. Resampling
uses the existing `resample_poly_hq` twice, replaying full offline context and
trimming to the original length. The adapter introduces no lookahead; learned
capture response/phase, bias and DC are preserved, not normalized or removed.
Silence/impulse checks on generated zero-bias captures do not guarantee the
response of an arbitrary user capture.

`NamModel.state(channels)` and `NamModel.process(audio, state)` are the raw,
stateful model API. `infer(x, sr, resolved)` returns audio plus reproducibility
facts; `infer_blocks` is full offline replay before resampling, not independently
resampled chunks. Raw stateful processing and offline transport replay are both
tested at 64/1024/full boundaries. Reference inference is offline and prioritizes
repeatability; no real-time speed claim is made.

Register a user-supplied capture explicitly with:

```python
from mankomix.dspx.bb import nam
nam.register(capture_path, id='my_capture', source_url=original_distribution_url,
             license_weights=user_declared_license, evidence_url=license_url)
```

Registration validates the file, uses existing `core.registry.model_register`,
then enriches that local BYOW entry with source URL, architecture, sample rate,
format, adapter revision, SHA-256, byte size, separate code/weights licenses,
primary reference-license evidence and the fixed manufacturer-affiliation
caveat. It neither copies nor downloads weights. Capture rights are declared by
the user; a reference implementation's MIT license does not license a capture.
No official entry, default capture or capture weights are bundled. Render-time
lookup re-hashes through BB-16 and verifies the actual bytes again before parse.

The format references are
[neural-amp-modeler v0.9.0](https://github.com/sdatkinson/neural-amp-modeler/tree/102333bf1c2c9f4255d73b8712ad3ecb0d8af275)
(`nam/models/wavenet.py`, `nam/models/recurrent.py`, MIT, copyright 2024 Steven
Atkinson) and
[NeuralAmpModelerCore](https://github.com/sdatkinson/NeuralAmpModelerCore/tree/d3189ed482ded880c128bf312941266c4fa5ceec)
(`NAM/lstm.cpp`, format-version documentation, MIT, copyright 2023 Steven
Atkinson). Their pinned LICENSE files were opened and checked on 2026-11-17;
URLs/dates are in `nam.REFERENCES`. No upstream implementation is bundled.

`procs/amp_sim.py` is track/offline/model-backend only, with required explicit
model, input -24..24 dB/default 0, output -36..12 dB/default 0, and
`fallback=error` by default. Only missing local weights permit the explicit
`fallback=amp_basic` substitute, which uses the existing generic amplifier's
defaults after input gain and before output gain. Its different sound, actual
parameters and reason are recorded alongside before/after meters and capture
license/hash. Invalid IDs, kinds, configurations and hashes do not fall back.
Empty model is only an internal declaration sentinel for the existing catalogue
default-validation contract; execution rejects it and JSON Schema requires a
nonempty model. No capture is selected implicitly.

Public `implemented=False` remains until the core owner connects standard Mix
Report model/fallback facts and validates model files before track-cache reuse.
Engine-step stats and BB-16 `report_records` already expose the facts. Tests
enable the processor only within an isolated fixture to exercise this path.

Model-free tests: `python -B -m pytest -q -p no:cacheprovider tests/test_tk_w5b.py`.
The optional external test requires `MANKOMIX_W5B_MODEL`, independently pinned
`MANKOMIX_W5B_MODEL_SHA256` and `MANKOMIX_W5B_EXPECTED_HASH`, plus
`MANKOMIX_W5B_SOURCE_URL` and `MANKOMIX_W5B_LICENSE_WEIGHTS`; an optional license
evidence URL is `MANKOMIX_W5B_LICENSE_URL`. Known input is mono at the capture
sample rate, `rate//4+127` samples, 0.1*sin(220 Hz)+0.03*sin(440 Hz), gains zero.
No capture variable means skip; no test downloads or silently accepts a newly
computed output hash.
