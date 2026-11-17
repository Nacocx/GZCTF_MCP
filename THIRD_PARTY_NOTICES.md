# Third-party notices

## WebSocketReflectorX (wsrx)

- Upstream: https://github.com/XDSEC/WebSocketReflectorX
- CLI version pinned by this project's installer: 0.6.2
- License: MIT; Copyright (c) 2023 XDSEC.
- Complete upstream license: [licenses/WebSocketReflectorX-MIT.txt](licenses/WebSocketReflectorX-MIT.txt).
- Integration: invokes an independently installed, unmodified `wsrx connect` executable as a managed subprocess. This project does not vendor its Rust implementation or bundle the executable in the Python wheel.
- Packaged notice/license: `gzctf_mcp/_licenses/THIRD_PARTY_NOTICES.md` and `gzctf_mcp/_licenses/WebSocketReflectorX-MIT.txt`.

Preserve the upstream copyright and permission notice with copies or substantial portions of the software. If redistributing an executable, also retain applicable notices for its transitive dependencies; the project's MIT license does not automatically cover every dependency.

## GZCTF

This project communicates with the GZCTF HTTP/WebSocket APIs. The local GZCTF clone is ignored and is not part of this distribution. This project does not relicense or redistribute GZCTF source, branding or restricted components. See the upstream repository's own license and notices for deployments of GZCTF.

API fields, permission masks, scoring parameter encoding, and encrypted API payload compatibility were studied against GZCTF commit `cc12f65fe9cd9eb2a94ccfcb3604a81e394e0296`. In particular, the API encryption format was referenced from `src/GZCTF/ClientApp/src/utils/Crypto.ts`. This is not a claim of clean-room development. The source-origin review and its limits are recorded in `docs/source-origin-review.md`; choosing MIT for the adapter does not replace any applicable third-party obligations.

## This project's own license

The original GZCTF MCP adapter code is licensed under the MIT License.
Copyright (c) 2026 Nacocx. See the root `LICENSE`, included in the Python distribution's license files.

This license choice does not relicense GZCTF, WebSocketReflectorX, their trademarks, or other third-party dependencies. Their respective licenses and notices remain applicable.
