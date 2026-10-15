# SPR implementation

SPR is now included in the Neonize source pinned by `requirements.txt` at commit
`9e188d19ca6f017f1dc6064b5a338c21194fcead` (the source submitted in
[krypton-byte/neonize PR #224](https://github.com/krypton-byte/neonize/pull/224)).

The `.patch` files in this directory are historical implementation snapshots.
Do not apply them over the pinned source. Install the dependency and build its
matching native library with:

```bash
python -m pip install -r requirements.txt
python scripts/build_neonize_spr.py
```

The native build requires Go 1.26.0+, CGO, and a C compiler. The script checks
the exact source commit and exported `SendSPRMessage` symbol before replacing
the installed library.
