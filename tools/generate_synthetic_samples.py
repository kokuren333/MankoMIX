"""Reproduce original sample WAVs outside the repository, or print hashes only."""
import argparse
import hashlib
import json
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from mankomix.dspx.bb.samples import synthetic_bytes


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output-dir', type=Path)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    if args.output_dir and (args.output_dir.resolve() == root or root in args.output_dir.resolve().parents):
        parser.error('audio output must be outside the repository')
    result = {}
    for id in ('synth_kick_a', 'synth_snare_a', 'synth_hat_a'):
        data = synthetic_bytes(id)
        result[id] = hashlib.sha256(data).hexdigest()
        if args.output_dir:
            args.output_dir.mkdir(parents=True, exist_ok=True)
            (args.output_dir/(id+'.wav')).write_bytes(data)
    print(json.dumps(result, sort_keys=True, indent=2))


if __name__ == '__main__':
    main()
