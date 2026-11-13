"""Music-information analysis and mix-level perceptual proxy metrics (SPEC 4.2, 6.3).

Submodules (import them directly; nothing heavy is imported here):

- ``erb``        ERB / Bark scales, ERB band layouts, ISO 226:2003 weights, ERB LTAS
- ``music``      BPM, beats, key, tonic frequency, loudness sections, note values
- ``perceptual`` 2mix proxies P-01, P-11, P-17, P-19, P-20 and ``range_penalty``

No librosa / Essentia / aubio / madmom: everything is numpy + scipy.
"""
