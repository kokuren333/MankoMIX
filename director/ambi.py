"""Top-level, project-independent Ambisonic file conversions (T05-07)."""
from __future__ import annotations

import os
from pathlib import Path

import numpy as np
import soundfile as sf

from mankomix.core.errors import EnvironmentProblem, InputError
from mankomix.dspx.bb import ambisonics as A


OPERATIONS = ("encode", "rotate", "decode", "convert", "info")


def register(subparsers, common):
    """Register one top-level group; leave direction and the engine untouched."""
    spatial = subparsers.add_parser("spatial", parents=[common],
                                    help="project-independent spatial audio file conversion")
    groups = spatial.add_subparsers(dest="subcommand", metavar="SUBCOMMAND", required=True)
    ambi = groups.add_parser("ambi", parents=[common], help="AmbiX ACN/SN3D, orders 1..3",
                            description="x=front, y=left, z=up; positive azimuth=left. "
                            "Rotation: roll, pitch, yaw (Rz Ry Rx). Outputs: float64 WAV.")
    commands = ambi.add_subparsers(dest="ambi_command", metavar="SUBCOMMAND", required=True)
    descriptions = {
        "encode": "encode a mono/stereo point source (stereo is averaged)",
        "rotate": "rotate AmbiX: roll then pitch then yaw, right-handed axes",
        "decode": "decode to a cardioid pair or virtual-speaker binaural stereo",
        "convert": "convert first-order FuMa WXYZ and AmbiX WYZX",
        "info": "inspect order, component levels and uncertain normalization",
    }
    for name in OPERATIONS:
        p = commands.add_parser(name, parents=[common], help=descriptions[name],
                                description=descriptions[name])
        p.add_argument("--in", dest="input", required=True, help="input audio file")
        p.set_defaults(func=run)
        if name != "info":
            p.add_argument("--out", required=True, help="explicit output .wav file (float64)")
        if name == "encode":
            p.add_argument("--order", type=int, choices=(1, 2, 3), default=1)
            p.add_argument("--azimuth", type=float, default=0., help="-180..180 degrees, positive left")
            p.add_argument("--elevation", type=float, default=0., help="-90..90 degrees, positive up")
        elif name == "rotate":
            for key in ("yaw", "pitch", "roll"):
                p.add_argument("--"+key, type=float, default=0.)
        elif name == "decode":
            p.add_argument("--to", choices=("stereo", "binaural"), required=True)
            p.add_argument("--angle", type=float, default=90., help="cardioid pair at +/- angle, 0..180")
            p.add_argument("--hrtf", default="model_sphere", help="registered BB-24 HRTF ID")
        elif name == "convert":
            p.add_argument("--from", dest="source", choices=("fuma", "ambix"), required=True)
            p.add_argument("--to", choices=("fuma", "ambix"), required=True)


def _output_path(source, name):
    target = Path(name)
    if (target.resolve() == source.resolve() or
            (target.exists() and os.path.samefile(source, target))):
        raise InputError("--out must not refer to the input file (including links)")
    if target.suffix.lower() not in (".wav", ".wave"):
        raise InputError("--out must be a .wav or .wave file (float64 WAV)")
    if not target.parent.is_dir() or target.is_dir():
        raise InputError("--out requires an existing parent directory and a file path")
    return target


def _info(x):
    order = A.order_for_channels(x.shape[1])
    levels = []
    for k in range(x.shape[1]):
        peak = float(np.max(np.abs(x[:, k]))) if len(x) else 0.
        rms = peak*float(np.sqrt(np.mean((x[:, k]/peak)**2))) if peak else 0.
        n = int(np.sqrt(k))
        levels.append({"acn": k, "degree": n, "m": k-n*(n+1), "rms": rms,
                       "rms_dbfs": float(20*np.log10(rms)) if rms else None, "peak": peak})
    return {"order": order, "components": levels,
            "normalization": {"estimate": "unknown", "assumed_for_processing": "ACN/SN3D",
                              "confidence": "undetermined",
                              "basis": "Channel count gives order; samples alone cannot identify "
                                       "channel order or normalization (including FuMa for four channels)."}}


def run(args):
    source = Path(args.input)
    if not source.is_file():
        raise InputError("input audio file does not exist")
    target = None if args.ambi_command == "info" else _output_path(source, args.out)
    try:
        x, sr = sf.read(source, dtype="float64", always_2d=True)
    except (RuntimeError, ValueError, OSError) as exc:
        raise InputError("input must be a readable audio file") from exc
    if not np.isfinite(x).all():
        raise InputError("input audio must contain only finite samples")
    result = {"command": "spatial ambi "+args.ambi_command, "sample_rate_hz": sr,
              "frames": len(x), "input_channels": x.shape[1]}
    try:
        if args.ambi_command == "info":
            return result | _info(x)
        if args.ambi_command == "encode":
            y = A.encode(x, args.order, args.azimuth, args.elevation)
            result.update(order=args.order, layout="ACN/SN3D", stereo_input="arithmetic mean")
        elif args.ambi_command == "rotate":
            order = A.order_for_channels(x.shape[1])
            y = x @ A.rotation_matrix(order, args.yaw, args.pitch, args.roll).T
            result.update(order=order, layout="ACN/SN3D", rotation="Rz(yaw) Ry(pitch) Rx(roll)")
        elif args.ambi_command == "decode":
            if args.to == "stereo":
                y = A.stereo(x, args.angle)
                result.update(cardioid_angle_deg=args.angle)
            else:
                y, details = A.binaural(x, sr, args.hrtf)
                result.update(details)
            result.update(layout=args.to)
        else:
            y = A.convert(x, args.source, args.to)
            result.update(order=1, layout="ACN/SN3D" if args.to == "ambix" else "FuMa WXYZ")
        if not np.isfinite(y).all():
            raise ValueError("conversion produced non-finite samples")
    except ValueError as exc:
        # BB-24 ParamError also derives from ValueError; retain CLI input errors.
        raise InputError(str(exc)) from exc
    try:
        with sf.SoundFile(target, "w", samplerate=sr, channels=y.shape[1],
                          format="WAV", subtype="DOUBLE") as output:
            # libsndfile's default floating WAV PEAK chunk contains wall time.
            # Documented SFC_SET_ADD_PEAK_CHUNK (0x1050), before any audio write:
            # https://libsndfile.github.io/libsndfile/command.html
            if sf._snd.sf_command(output._file, 0x1050, sf._ffi.NULL, 0) != 0:
                raise RuntimeError("could not disable the timestamped PEAK chunk")
            output.write(y)
    except (RuntimeError, ValueError, OSError) as exc:
        raise EnvironmentProblem("could not write the explicit output WAV file") from exc
    return result | {"output_channels": y.shape[1], "output_subtype": "DOUBLE"}
