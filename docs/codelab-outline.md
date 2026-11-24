# Codelab outline: "Find 10 bugs in QNX build files"

> DRAFT OUTLINE ONLY — for the QNX Global Hackathon "Best Codelab /
> Tutorial" bonus prize ($3,500). Not yet written as a full codelab.

## Concept

A hands-on tutorial that teaches QNX 8.0 build files by breaking them.
The reader is given a small, working QNX project (a bootable image for
QEMU plus a driver and a resource manager), then ten bugs are introduced
one at a time. For each bug the reader runs `qnxbuild-lint`, reads the
finding, fixes the file, and re-runs the checker until it is clean —
and then boots the fixed image in QEMU to see the difference.

Format: a written codelab (web page + repository) with copy-pasteable
commands. Estimated time: 60–90 minutes. Prerequisites: a Linux host,
Python 3.8+, QNX SDP 8.0 (free via QNX Everywhere), QEMU.

## Learning objectives

After finishing, the reader can:

1. Read a mkifs `.build` file and explain what the boot section, the
   startup script and the file entries do.
2. Explain how the QNX recursive-make system fits together
   (`qconfig.mk` → `common.mk` → `qmacros.mk` → `qtargets.mk`).
3. Spot the five most common QNX API misuses in C code.
4. Use a static checker in CI so these bugs never reach a board.

## The 10 exercises

Each exercise: one broken file, the `qnxbuild-lint` finding, the fix,
and a "why it matters" note (what happens on real hardware if the bug
ships).

| # | Bug | Check | What breaks on the board |
|---|-----|-------|--------------------------|
| 1 | Unclosed `{` in the startup script | B01 | `mkifs` fails; no image at all |
| 2 | `[imag=...]` typo in an attribute | B02 | Attribute silently ignored; wrong image load address |
| 3 | Boot section with no `startup-*` binary | B05 | Hardware never initialised; kernel panics early |
| 4 | Boot section with no `procnto` | B06 | No microkernel in the image |
| 5 | File entry points at a host file that does not exist | B07 | `mkifs` fails at image build time |
| 6 | `procmgr_symlink` destination is a relative path | B11 | Symlink created in the wrong place; `/usr/lib/ldqnx.so.2` missing at runtime |
| 7 | Inline `.sh` file without a `#!` shebang | B12 | Script cannot be executed at boot |
| 8 | `common.mk` without `qtargets.mk` | M02 | `make` succeeds but builds nothing |
| 9 | `ThreadCtl(0, 0)` — no `_NTO_TCTL_IO` | C01 | Driver cannot access hardware I/O; fails with `EPERM` |
| 10 | `resmgr_attach()` with no dispatch context | C03 | Resource manager never receives a message; clients hang |

## Structure of the finished codelab

1. **Setup** (10 min): install the SDP, clone the example project,
   build it once, boot it in QEMU, confirm it works.
2. **Part 1 — the image file** (25 min): exercises 1–7 on
   `images/qemu.build`.
3. **Part 2 — the makefiles** (10 min): exercise 8 on `common.mk`.
4. **Part 3 — the C code** (20 min): exercises 9–10 on the driver and
   the resource manager.
5. **Wrap-up** (5 min): add `qnxbuild-lint` to a CI workflow
   (example GitHub Actions job included), checklist of the 25 checks,
   where to go next (QNX docs, `qnxbuild-lint --list-checks`).

## What still needs doing to ship it

- [ ] Build the example QEMU project used by the exercises (needs the
      QNX SDP 8.0 — pending, see the main README).
- [ ] Verify each exercise end-to-end: bug in → linter finding →
      fix → clean run → successful QEMU boot.
- [ ] Write the full codelab text with screenshots/terminal output.
- [ ] Publish the codelab URL and link it in the Devpost submission
      (the "Best Codelab / Tutorial" field).
