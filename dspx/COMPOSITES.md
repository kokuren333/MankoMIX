# W3f fixed composite mappings

All amounts are in [0,1]. Stages with zero amount are omitted; noise at
−120 dBFS is omitted. Child IDs are assigned by BB-00. Each seeded child
receives the source `seed`; the engine additionally keys it by its child ID.
These are fixed formulas, not measured equipment presets.

## Cassette

| tape_type | bias | base gap_loss | base LP (Hz) |
|---|---:|---:|---:|
| normal | .45 | .65 | 10000 |
| chrome | .55 | .45 | 14000 |
| metal | .60 | .30 | 16000 |

1. If wobble>0: wow_flutter wow_depth=1.5*wobble, flutter_depth=.4*wobble.
2. If saturation>0 or age>0: tape speed=3.75, saturation=saturation,
   drive_db=6*saturation, bias=table, gap_loss=min(1,base+.35*age).
3. If age>0: cut_filter kind=lpf, freq_hz=baseLP*(1−.5*age).
4. If hiss_db>−120 or age>0: noise_bed hiss_db=hiss_db, dropout=.3*age.
5. If narrow>0: stereo width=1−.5*narrow, no crossover or mono restriction.

The LP amount is age. At age=0 the dedicated LP is omitted, including when
saturation>0; tape itself still applies its playback-loss filter.

## Lofi

| style | wow max (%) | flutter max (%) | drive max (dB) | bits removed max | minimum clock (Hz) | HP max (Hz) | LP min (Hz) | noise components |
|---|---:|---:|---:|---:|---:|---:|---:|---|
| tape | 1.5 | .4 | 12 | 12 | 12000 | 30 | 10000 | hiss |
| vinyl | .8 | .2 | 9 | 10 | 16000 | 40 | 12000 | crackle, rumble |
| digital | .3 | .08 | 18 | 20 | 4000 | 20 | 18000 | white hiss |
| radio | .2 | .05 | 15 | 16 | 8000 | 300 | 3500 | hiss, hum |

1. wow_flutter depths = table maxima*wobble.
2. Existing saturator drive_db=table drive*dirt, mode=tanh.
3. bitcrush bits=24−table bitsRemoved*crunch;
   rate_hz=192000*(table minimumClock/192000)^crunch; antialias=false.
4. tone>0 expands into two cut_filter children, HP then LP:
   HP=max(10,table HP*tone), LP=20000*(table LP/20000)^tone.
   Both use the existing default 24 dB/oct Butterworth minimum phase.
5. noise_bed enabled components have level=−120+(120+peak)*noise.
   Component peaks: hiss −45, crackle −35, rumble −45, hum −50 dBFS.
   All other components keep their disabled defaults. Digital uses white
   hiss; other styles use the existing tape hiss colour.
6. Existing reverb rt60_s=.3, predelay_ms=0, mix=.25*space.
   Existing reverb has no seed parameter; its normal engine seed is used.

At 44.1/48/96 kHz every cutoff is below 0.98*Nyquist. At lower sample
rates existing child runtime frequency checks can reject a rack; this map
does not silently clamp a child cutoff using an unknown sample rate.

## Empty expansion

Both expanders return [] at all-zero amounts. BB-00 passes the input
through bit for bit and retains one audit record at the source ID, with
`composite_of` holding the source item and `expansion: []`. No child
processor is inserted. This record uses the engine bypass path and has
no backend. Nonempty racks retain their original child expansion and IDs.
