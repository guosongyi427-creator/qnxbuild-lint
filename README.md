# qnxbuild-lint

A static checker for QNX 8.0 project build files. It catches the mistakes
that only show up after a long `make` + `mkifs` cycle — unbalanced braces
in a `.build` file, a boot image with no `procnto`, a `common.mk` that
never includes `qtargets.mk`, a `ThreadCtl()` call with the wrong flags —
and reports them in seconds, with no QNX SDP installed.

Built for the **QNX Global Hackathon** (Devpost), category
**Developer Tooling & Host Tools**. It is a Linux host tool: it helps
you build software targeting QNX 8.0.

## What it checks

25 checks across three file classes:

| ID | Severity | What it finds |
|----|----------|---------------|
| B01 | error | Unbalanced `{`/`}` braces or `[`/`]` brackets in a `.build` file |
| B02 | warning | Unknown attribute inside `[...]` (mkifs ignores it silently) |
| B03 | error | No `[virtual=...] boot = {` section — no bootable image |
| B04 | error | No `[+script] startup-script = {` section |
| B05 | error | Boot section invokes no `startup-<board>` binary |
| B06 | error | Boot section invokes no `procnto` (no microkernel) |
| B07 | error | File entry references a host file (explicit path) that does not exist |
| B08 | warning | Referenced binary not found anywhere in the project tree |
| B09 | warning | Same target path listed twice in the image |
| B10 | error | Malformed `[perms=]` (not octal) or `[uid=]`/`[gid=]` (not numeric) |
| B11 | warning | `procmgr_symlink` with a non-absolute destination or odd source |
| B12 | warning | Inline `.sh` file written into the image without a `#!` shebang |
| M01 | error | `common.mk` never includes `$(QCONFIG)` / never defines `QCONFIG` |
| M02 | error | `common.mk` missing `qmacros.mk` / `qtargets.mk` |
| M03 | error | `common.mk` never assigns `NAME` |
| M04 | warning | `USEFILE` points at a file that does not exist |
| M05 | warning | `INSTALL_ROOT_nto` is a hardcoded absolute path |
| M06 | warning | (Non top-level) `Makefile` contains no `include` line |
| M07 | warning | `USE_INSTALL_ROOT` set but `INSTALL_ROOT_nto` not defined |
| C01 | error | `ThreadCtl()` called without a `_NTO_TCTL_*` flag |
| C02 | warning | `ChannelCreate()` with nothing connecting to it in the file |
| C03 | error | `resmgr_attach()` without a dispatch context |
| C04 | warning | `name_attach()` without `name_detach()` |
| C05 | warning | `InterruptAttach[Event]()` without `InterruptDetach()` |
| C06 | error | `ChannelCreate()` flags neither `0` nor a `_NTO_CHF_*` constant |

Run `./qnxbuild-lint --list-checks` for the same list with full
descriptions.

## Install

Requires Python 3.8+ and nothing else (standard library only).

```sh
git clone <this repo>
cd qnxbuild-lint
./qnxbuild-lint --list-checks
```

Optional: copy the launcher somewhere on your `PATH`:

```sh
cp qnxbuild-lint qnxbuild_lint.py /usr/local/bin/
```

## Usage

```sh
# Check a whole project directory (recursive)
./qnxbuild-lint my-bsp/

# Check individual files
./qnxbuild-lint images/rpi4.build src/hardware/devb/common.mk

# Machine-readable output for CI
./qnxbuild-lint --format json my-bsp/

# Fail the build on warnings too
./qnxbuild-lint --fail-on warning my-bsp/
```

Exit codes: `0` = no findings at or above the failure threshold,
`1` = findings at or above the threshold, `2` = usage error.
The default threshold is `error`; warnings do not fail a CI job
unless you pass `--fail-on warning`.

### Example output

```text
$ ./qnxbuild-lint tests/fixtures/bad_dup_perms.build
qnxbuild-lint 0.1.0

tests/fixtures/bad_dup_perms.build
  9: [B08 warning] Binary 'tool1' not found anywhere in the scanned project tree; it may be built by make or live in ${QNX_TARGET}.
  9: [B10 error] perms value '0999' is not valid octal (expected e.g. 0755 or 4755).
  11: [B09 warning] Target path '/bin/ksh' already listed at line 10.

Checked 1 file(s), 25 check(s) available: 1 error(s), 2 warning(s), 0 info
```

```text
$ ./qnxbuild-lint tests/fixtures/good-project
qnxbuild-lint 0.1.0

Checked 4 file(s), 25 check(s) available: 0 error(s), 0 warning(s), 0 info
```

## What it does not do

* It is a **static** checker: it reads files as text and never executes
  them. It never invokes `make`, `mkifs` or `qcc`, and it does not need
  the QNX SDP.
* References through `${QNX_TARGET}` are skipped — they can only be
  resolved with the SDP installed.
* **B08** (binary not found in the project tree) is a warning, not an
  error: binaries are normally built by `make` into an `install/` tree
  before `mkifs` runs. Run the linter after `make install` for a
  definitive answer.
* Pairing checks (C02–C05) are per-file: a channel created in one file
  and connected in another will still be reported. Treat those warnings
  as prompts, not verdicts.

## Validation against real projects

The checker's formats were studied from the public QNX BSP for the
Raspberry Pi 4 (`qnx/bsp_raspberrypi-bcm2711-rpi4`, including its
829-line `images/rpi4.build`) and the QNX ports build files
(`qnx-ports/build-files`). To run the checker against those trees
yourself:

```sh
git clone https://github.com/qnx/bsp_raspberrypi-bcm2711-rpi4.git
git clone https://github.com/qnx-ports/build-files.git
./qnxbuild-lint bsp_raspberrypi-bcm2711-rpi4 build-files
```

Note: the reference trees contain build products that do not exist
until `make` runs, so expect B08 warnings until the projects are
built. SDP-dependent validation — cross-compiling a checked project
with `qcc` and booting the resulting image in QEMU — is a separate
step that requires the QNX SDP 8.0 (free for non-commercial use via
QNX Everywhere, https://qnx.software) and is not part of this tool.

## Tests

```sh
python3 tests/run_tests.py
```

23 tests: a clean synthetic project must produce zero findings, and
each deliberately broken fixture must produce exactly its expected
check IDs. The fixtures in `tests/fixtures/` are synthetic examples
written for this project.

## License

MIT — see `LICENSE`.
