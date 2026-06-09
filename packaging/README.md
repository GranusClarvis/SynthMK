# SynthMK packaging

`build_mkp.sh` builds a deterministic, secret-free **MKP-style package skeleton**
under `dist/`:

```
dist/synthmk-<version>.mkp        # gzip tar, reproducible (fixed mtime/owner)
dist/synthmk-<version>/           # staged tree
  info                            # Checkmk package metadata (python-dict)
  info.json                       # JSON mirror
  local/
    lib/check_mk_agent/local/300/synthmk_check.sh   # the agent local-check
    share/synthmk/{runner,flows,checkmk,docs,...}   # runtime payload
```

Run it:

```bash
make package        # or: ./packaging/build_mkp.sh
```

The build is **deterministic** — the same source produces a byte-identical
archive (sorted entries, fixed mtime/owner), so a checksum can gate CI.

## What this is / is not

- **Is:** the file layout, metadata, and a reproducible tarball an MKP needs,
  plus a clean payload with no `.git`, caches, `.env`, or screenshots.
- **Is not yet:** Checkmk's exact per-part member-tarball wrapping. A real MKP is
  a tar of `info` + `info.json` + one member tarball per file-part. Producing
  those member tarballs (ideally via `mkp` / `omd` on a real site so checksums
  match Checkmk's own packer) is the next step.

## TODO toward an installable MKP

1. On a Checkmk 2.x site, lay these files into the site tree and run
   `mkp package packaging/info` to let Checkmk pack the member tarballs.
2. Pin `version.min_required` against the lowest Checkmk version actually tested.
3. Add a CI job that runs `make package` twice and asserts identical sha256.
