# IR registries and convolution

BB-08 lives in `bb/asset_registry.py` and `bb/ir.py`. The JSON catalogue
`registry/irs.json` contains original synthesis metadata and pinned PCM32 WAV
hashes, without audio payloads. Reproduce bytes with
`python -B tools/generate_synthetic_irs.py`; provide `--output-dir` to write
WAVs outside the repository. Runtime synthesis stays in memory.

`AssetRegistry(name, catalog_path, metadata, generate=None, validate=None)`
provides the common BB-24 rules. A later registry supplies a metadata reader,
an official-payload provider and optional format validator. No HRTF or sample
catalogue is installed by W2c. Official payloads require original synthesis or
primary CC0 evidence. The IR specialization requires original synthesis only.

Use `IRS.register_file(path, id=..., license_spdx=..., kind="room")` for a
local registration. `kind` defaults to room when omitted. Cabinet registrations
use `kind="cabinet"`. The source is hashed and left in place. The registration
lives in `settings_dir()/byo_irs.json`, never in the project or catalogue.
`evidence`, `checked_on`, `usage_restrictions` and `replace` are optional
registration arguments. License is mandatory; `unknown` remains visible in
registration results and render statistics. Removing a registration leaves the
source file untouched. No download operation is provided.

`IRS.resolve(id)` returns public metadata. `IRS.load(id)` verifies fresh source
bytes and returns bytes, public metadata and notices. `load_ir(id, sr)` decodes
1/2/4 channels and reuses `resample_poly_hq`. Its bounded in-memory cache key
contains source SHA-256, target rate, converter version and converted float64
SHA-256. Cache hits still verify source bytes; returned coefficients are copies.
Absolute local paths never appear in these public records.

The shared `prepare_ir`, `kernel` and `convolve_ir` functions use BB-07.
Four-channel ordering is LL, LR, RL, RR (input then output). Mono input is sent
to both matrix inputs; stereo IRs expand mono into stereo. Mix zero bypasses
bit-exactly after provenance verification. The optional asset declaration
`allow_empty=True` permits only the unused cabinet `ir_b` empty string.

The decay window uses the prepared source's broadband Schroeder T20:
`exp(-ln(1000)*t*(1/decay-1)/T20)`. A one-tap or silent IR has no fitted T20
and needs no decay change. Energy normalization divides by the square root of
mean input-path energy (one input for mono, two for diagonal/true stereo). Peak normalization divides by the largest coefficient.
Minimum phase reuses BB-07's real cepstrum per stored channel. Dual cabinet IRs
are normalized individually, delayed and blended, then wet-filtered and measured.
R-10 statistics include provenance and both microphone assets.

## Early-reflection geometry

`bb/image_source.py` fixes the listener at `(0.50 W, 0.43 L, 0.47 H)`.
The source offset is `distance*(sin(pi*azimuth/2), cos(pi*azimuth/2), 0)`.
The source must lie strictly inside the room; invalid dimension/distance/angle
combinations raise ParamError rather than changing the requested distance.
The center on the width axis makes azimuth sign reversal mirror the outputs.
Sound speed is 343 m/s. Image order is the Manhattan norm of the three integer
image coordinates; all orders up to the limit are enumerated. Path gain is
`(1-absorption)**(order/2)/distance`, followed by equal-power horizontal pan.
BB-09 supplies windowed-sinc placement. A second-order Butterworth lowpass is
applied once per reflection; cutoff at or above .45 sr is bypassed. Wet filters
and width are applied inside the strict finite support. There is no scene mapping.
An early-only finite response has no declared diffuse-field RT60 target.

## Sources and existing APIs

The image-source expansion is independently implemented from the specification
and the mathematical model of Allen and Berkley, *Image method for efficiently
simulating small-room acoustics*, JASA 65(4), 943?950 (1979),
https://doi.org/10.1121/1.382599 . The author's public paper was checked at
https://jontalle.web.engr.illinois.edu/Public/Allen-PDFs/PDFs/AllenBerkley79.pdf .
No reference implementation or product output was copied.

Existing NumPy 2.5.3 (BSD-3-Clause), SciPy 1.18.1 (BSD-3-Clause) and soundfile
0.14.0 (BSD-3-Clause) APIs are used. New calls are NumPy array operations and
PCG64, scipy.signal butter/lfilter/sosfilt, and soundfile.read. Existing BB-07
supplies FFT convolution and minimum phase; BB-09 supplies sinc reads and wet
filters; BB-10 supplies R-10 and self-duck/mix finishing. Every FFT uses workers=1.
Resampling follows the existing export kernel, using the public API documented at
https://docs.scipy.org/doc/scipy/reference/generated/scipy.signal.resample_poly.html .
All synthesis coefficients are original choices, with no external audio assets.
