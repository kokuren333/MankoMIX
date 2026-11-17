"""Register local NPZ HRIR sets; optionally convert simple SOFA files offline.

Runtime DSP never imports h5py. Conversion accepts SimpleFreeFieldHRIR with
standard listener axes, spherical degrees/metres, left/right receivers and a
single source radius. Other conventions fail explicitly rather than guessing.
No third-party code is copied; AES69/SOFA field definitions:
https://www.sofaconventions.org/mediawiki/index.php/SimpleFreeFieldHRIR
"""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def convert_sofa(source, destination):
    """Convert to right-positive azimuth NPZ; preserve Data.Delay in samples."""
    import numpy as np
    try:
        import h5py
    except ImportError as exc:
        raise ValueError("SOFA conversion requires optional h5py in the registration environment") from exc
    from mankomix.dspx.bb.delayline import fractional_delay
    from mankomix.dspx.bb.hrtf import decode_npz

    def text(v):
        return v.decode("utf-8") if isinstance(v, bytes) else str(v)

    with h5py.File(source, "r") as f:
        if text(f.attrs.get("SOFAConventions", "")) != "SimpleFreeFieldHRIR":
            raise ValueError("only SimpleFreeFieldHRIR is supported")
        pos = f["SourcePosition"]
        units = text(pos.attrs.get("Units", "")).lower().replace(" ", "")
        if text(pos.attrs.get("Type", "")).lower() != "spherical" or units not in (
                "degree,degree,metre", "degree,degree,meter"):
            raise ValueError("SourcePosition must be spherical degrees/degrees/metres")
        p = np.asarray(pos, dtype=float)
        if p.ndim != 2 or p.shape[1] != 3 or np.any(p[:, 2] <= 0) or not np.allclose(p[:, 2], p[0, 2]):
            raise ValueError("one positive source radius is required")
        for key, expected in (("ListenerView", [1, 0, 0]), ("ListenerUp", [0, 0, 1])):
            if key in f and not np.allclose(np.asarray(f[key]), expected):
                raise ValueError("nonstandard listener axes are unsupported")
        for key in ("ListenerPosition", "EmitterPosition"):
            if key in f and not np.allclose(np.asarray(f[key]), 0):
                raise ValueError("nonzero listener or emitter offsets are unsupported")
        if "ReceiverPosition" not in f:
            raise ValueError("ReceiverPosition must identify left then right ears")
        receivers = f["ReceiverPosition"]
        if text(receivers.attrs.get("Type", "")).lower() != "cartesian":
            raise ValueError("ReceiverPosition must be Cartesian")
        r = np.asarray(receivers).reshape(2, 3, -1)
        if not (np.all(r[0, 1] > 0) and np.all(r[1, 1] < 0)):
            raise ValueError("receiver order must be left then right")
        rate = np.asarray(f["Data.SamplingRate"]).ravel()
        if len(rate) != 1 or not float(rate[0]).is_integer():
            raise ValueError("one integer sampling rate is required")
        sr = int(rate[0])
        h = np.asarray(f["Data.IR"], dtype=np.float64)
        if h.ndim != 3 or h.shape[:2] != (len(p), 2):
            raise ValueError("Data.IR must have shape measurements,2,taps")
        h = h.transpose(0, 2, 1).copy()
        if "Data.Delay" in f:
            delay = f["Data.Delay"]
            d = np.broadcast_to(np.asarray(delay), (len(p), 2)).copy()
            unit = text(delay.attrs.get("Units", "sample")).lower()
            if unit in ("second", "seconds"):
                d *= sr
            elif unit not in ("sample", "samples"):
                raise ValueError("Data.Delay units must be samples or seconds")
            if np.any(d < 0) or not np.isfinite(d).all() or np.max(d) > sr*.1:
                raise ValueError("Data.Delay must be finite, nonnegative and at most 100 ms")
            if np.any(d):
                h = np.pad(h, ((0, 0), (0, int(np.ceil(np.max(d)))+4), (0, 0)))
                h = np.stack([fractional_delay(row, delays[None, :]) for row, delays in zip(h, d)])
    import io
    out = io.BytesIO()
    az = -((p[:, 0]+180) % 360-180)
    np.savez(out, azimuth_deg=az, elevation_deg=p[:, 1], hrir=h, sr=np.int64(sr))
    decode_npz(out.getvalue())
    target = Path(destination)
    with target.open("xb") as stream:
        stream.write(out.getvalue())
    return target


def main():
    p = argparse.ArgumentParser(description=__doc__)
    sub = p.add_subparsers(dest="command", required=True)
    sub.add_parser("list")
    remove = sub.add_parser("remove"); remove.add_argument("id")
    convert = sub.add_parser("convert-sofa")
    convert.add_argument("source"); convert.add_argument("destination")
    add = sub.add_parser("register")
    add.add_argument("path"); add.add_argument("--id", required=True)
    add.add_argument("--license", required=True, dest="license_spdx")
    add.add_argument("--evidence-url"); add.add_argument("--checked-on", default="unknown")
    add.add_argument("--usage-restrictions", default="unknown")
    add.add_argument("--replace", action="store_true")
    args = p.parse_args()
    from mankomix.dspx.bb.hrtf import HRTFS
    if args.command == "list":
        result = {"official": HRTFS.catalog()["hrtfs"],
                  "byo": [HRTFS.resolve(e["id"]) for e in HRTFS.local()["hrtfs"]]}
    elif args.command == "remove":
        result = HRTFS.remove(args.id)
    elif args.command == "convert-sofa":
        convert_sofa(args.source, args.destination)
        result = {"converted": True}
    else:
        evidence = ([{"kind": "user_declaration", "url": args.evidence_url}]
                    if args.evidence_url else None)
        result = HRTFS.register_file(args.path, id=args.id, license_spdx=args.license_spdx,
                                     evidence=evidence, checked_on=args.checked_on,
                                     usage_restrictions=args.usage_restrictions, replace=args.replace)
    print(json.dumps(result, sort_keys=True, ensure_ascii=False))


if __name__ == "__main__":
    main()
