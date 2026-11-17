# Direction command extensions

Add one Python file per command. Each module exports `COMMANDS`, a list of
declarations. Modules are discovered once, sorted by filename; `_` helper modules
are ignored. An invalid declaration, duplicate path, overlapping extension leaf
or collision with an existing executable raises `ImportError`.

```python
def add_args(parser):
    parser.add_argument("--track", required=True)

def run(args):
    # Read args.project (global option), render/measure in memory, return evidence.
    return {"kind": "direction_example", "candidates": [], "confidence": "low"}

COMMANDS = [{
    "path": ("suggest", "example"),  # relative to `direction`
    "help": "Describe what this command measures and returns",
    "add_args": add_args,
    "run": run,
    "writes": False,
    # Optional; default is direction_suggest_example, planned only, not exposed.
    "mcp_planned": "direction_suggest_example",
}]
```

The CLI registers new groups automatically, and reuses existing groups (`ref`,
`edit`, etc.). Paths may have more than two components. Each component uses
lowercase letters, digits, underscores and hyphens (for example,
`("query", "limiter_headroom")`). Global `--project`, `--actor`, `--format`
and `--debug` work before or after the command. Existing command leaves cannot
be replaced. The existing `direction query AUDIO SPEC` invocation remains valid;
known new `query` subcommand names take precedence in that position. When query
extensions exist, query help lists them and mentions the legacy invocation.

`run(args)` must return a finite JSON object (no Path/numpy objects), with
deterministic ordering/rounding and no timestamps. The wrapper canonicalizes keys
and the existing CLI emitter prints the result. Raise `InputError` for bad user
inputs. Call existing director/core APIs for measurements without changing their
gates, profiles or defaults. Suggestions return candidate moves and measured
evidence with confidence/caveats; they do not apply candidates or track whether
the director uses them. Nothing registers an MCP tool: `cli_only()` supplies a
planned name and the direction-layer CLI-only reason to the existing MCP coverage
tables automatically. Their existing entries and coverage checks stay intact.

## Write contracts

Only `writes=False` and `writes="out_only"` are accepted. By default an extension
requires a project context (explicit `--project`, or the current project directory).
The optional declaration `project="optional"` also permits standalone file input;
`project="none"` never invokes the project resolver, even inside a project.
An optional command uses the project guard when a project is supplied or found in
cwd. Its callback still receives the original CLI args and must handle absent
project context. Declare input argument names with `inputs=("audio",)` (the
default); multiple-file arguments may contain a list/tuple of paths.

Without a project, the wrapper snapshots cwd and each input's directory (including
symlink targets). With `--out`, it also watches the nearest existing output parent
so newly created parents cannot hide sibling writes. Only the output subtree and
missing parent directories may change; inputs must remain byte-identical and
`--out` may not overlap them or cwd project state. These checks also run on errors.
With a project, optional commands additionally protect declared input files outside
the project. This remains a mutation detector over those scopes, not a filesystem
sandbox. Callbacks must not write elsewhere.

`direction preview codec --audio FILE` uses this optional context. Outside a
project it checks AAC, Opus, MP3 and Ogg Vorbis by default, or just `--codec` choices;
the existing verification backend determines availability. Numeric excerpts work
without a project; named project sections require a project. Omitting `--out`
returns JSON only, and supplying it saves the listening files there.

* `False`: the wrapper hashes every project file before/after execution, including
  `project.json`, `journal.jsonl` and every `directions/` ledger/document. Added,
  removed and modified files, directory entries and symlinks count as writes.
  Do not even create analysis caches. Prefer in-memory renders/measurements.
* `"out_only"`: `add_args` must define an **optional** `--out`. If omitted, return
  JSON only and make no filesystem changes; the full project read-only guard
  still runs, including on callback failure. If supplied, only that file or
  directory subtree can change. Creating its missing parent
  directories is allowed. `--out` cannot overlap project.json, journal.jsonl or
  directions/, cannot be the project directory, and cannot overwrite an existing
  path inside the project. Other project files must remain identical. For an
  external output, the wrapper also hashes its parent and rejects sibling writes.
  This is the same explicit-output model as listen pack, preview codec or MIDI
  extraction; it never permits a project-state/ledger change.

The check also runs when the callback raises. A violation becomes `InputError`
with relative changed paths. This is a before/after mutation detector, not a
security sandbox or rollback transaction: a defective callback's writes are
reported, not silently undone. Arbitrary unrelated filesystem locations are not
monitored. Test all callback outputs and side effects under tmp_path, including
both a successful command and an intentionally violating callback.

Do not add a production example command. Tests monkeypatch `COMMANDS` after
discovery (and `_loaded=True` when isolating discovery itself). Subsequent W4
commands should need only their module and tests, without CLI/table edits.
