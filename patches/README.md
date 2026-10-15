# SPR implementation

`requirements.txt` pins the Neonize source used by this gateway to commit
`596d5ac327f176a70472147f96d4dd674c67911c` from `Nauvalunesa/neonize`. The
upstream implementation is tracked in [krypton-byte/neonize PR #224](https://github.com/krypton-byte/neonize/pull/224).

The `.patch` files in this directory are historical implementation snapshots.
The pinned source commit is authoritative; do not apply these snapshots over
it. Install the dependency and build its matching native library with:

```bash
python -m pip install -r requirements.txt
python scripts/build_neonize_spr.py
```

The native build requires Go 1.26.0+, CGO, and a C compiler. The script checks
the exact source commit and exported `SendSPRMessage` symbol before replacing
the installed library. Restart the gateway after a successful build so the
runtime loads the new native library.
