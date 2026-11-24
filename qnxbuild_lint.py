#!/usr/bin/env python3
"""qnxbuild-lint - a static checker for QNX 8.0 project build files.

Scans a QNX project directory (or individual files) and checks three
classes of files for common mistakes:

  * mkifs ``.build`` image files (boot section, startup script,
    attributes, file entries, symlinks, permissions)
  * QNX recursive-make files (``common.mk`` / ``Makefile``)
  * C sources using QNX Neutrino APIs (``ThreadCtl``, channels,
    resource managers, interrupts, ...)

The tool uses only the Python standard library.  It is a *static*
checker: it reads files as text and never executes them, never invokes
``make``/``mkifs``/``qcc`` and never needs the QNX SDP installed.
Cross-compiling a checked project with ``qcc`` and booting the image
in QEMU is a separate, SDP-dependent validation step.

Usage:
    qnxbuild-lint [options] <path> [<path> ...]

Exit codes:
    0  no findings at or above the failure threshold
    1  findings at or above the failure threshold
    2  usage error (bad arguments, unreadable path)

Example:
    qnxbuild-lint --format json my-bsp/
    qnxbuild-lint --fail-on warning images/rpi4.build
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys

__version__ = "0.1.0"

SEVERITY_RANK = {"info": 0, "warning": 1, "error": 2}


# ---------------------------------------------------------------------------
# Check registry
# ---------------------------------------------------------------------------

class Check:
    """Metadata for one check."""

    def __init__(self, check_id, severity, title, description):
        self.id = check_id
        self.severity = severity
        self.title = title
        self.description = description

    def to_dict(self):
        return {
            "id": self.id,
            "severity": self.severity,
            "title": self.title,
            "description": self.description,
        }


CHECKS = {}


def _register(check_id, severity, title, description):
    CHECKS[check_id] = Check(check_id, severity, title, description)


# --- mkifs .build files ----------------------------------------------------
_register("B01", "error", "Unbalanced braces or brackets",
          "A '{' has no matching '}' (or vice versa), or a '[' attribute "
          "bracket is not closed on its line. mkifs will fail to parse "
          "the image definition.")
_register("B02", "warning", "Unknown attribute in [...]",
          "An attribute name inside [...] is not a known mkifs attribute "
          "(image, virtual, uid, gid, perms, type, search, optional, "
          "keeplinked, script, session, data, ...). It is probably a typo "
          "and mkifs will silently ignore it.")
_register("B03", "error", "No boot section",
          "No '[virtual=...] boot = {' section found. Without a boot "
          "section mkifs cannot produce a bootable image.")
_register("B04", "error", "No startup script",
          "No '[+script] startup-script = {' section found. The image "
          "would boot with no startup script.")
_register("B05", "error", "Boot section has no startup-* binary",
          "The boot section does not invoke a 'startup-<board>' binary. "
          "The board-specific startup program configures the hardware "
          "before procnto starts.")
_register("B06", "error", "Boot section has no procnto",
          "The boot section does not invoke procnto (procnto, "
          "procnto-smp, procnto-smp-instr, ...). The image would contain "
          "no microkernel.")
_register("B07", "error", "Referenced host file does not exist",
          "A file entry references a host file by an explicit relative "
          "path (or a [search=] directory) and that file is not present. "
          "mkifs will fail to build the image. References through "
          "${QNX_TARGET} are skipped: they need the SDP installed.")
_register("B08", "warning", "Referenced binary not found in project tree",
          "A bare binary name in a file entry was not found anywhere in "
          "the scanned project tree. It may be built later by make or "
          "live in ${QNX_TARGET}; run the linter after 'make install' "
          "for a definitive answer.")
_register("B09", "warning", "Duplicate target path in image",
          "The same target path is listed twice as a file entry. The "
          "later entry wins, which is rarely intended.")
_register("B10", "error", "Malformed perms/uid/gid attribute",
          "A [perms=] value is not valid octal (e.g. 0755, 4755), or a "
          "[uid=]/[gid=] value is not numeric.")
_register("B11", "warning", "procmgr_symlink looks wrong",
          "A procmgr_symlink call has a destination that is not an "
          "absolute path, or a source that is not a plausible path. The "
          "symlink will be created in the wrong place at boot.")
_register("B12", "warning", "Inline script file has no shebang",
          "An inline file whose name ends in .sh is written into the "
          "image without a '#!' line, so the shell cannot execute it "
          "directly.")

# --- QNX recursive-make files ----------------------------------------------
_register("M01", "error", "common.mk does not use QCONFIG",
          "A common.mk neither includes $(QCONFIG) nor defines QCONFIG. "
          "Without qconfig.mk the QNX recursive-make variables (CPU, "
          "SECTION, PROJECT_ROOT, ...) are undefined.")
_register("M02", "error", "common.mk missing qmacros.mk / qtargets.mk",
          "A common.mk does not include $(MKFILES_ROOT)/qmacros.mk and "
          "$(MKFILES_ROOT)/qtargets.mk. qtargets.mk is what actually "
          "builds the target.")
_register("M03", "error", "common.mk does not set NAME",
          "A common.mk never assigns NAME (directly or as an 'ifndef "
          "NAME' default). NAME is the name of the binary/library being "
          "built.")
_register("M04", "warning", "USEFILE points at a missing file",
          "The USEFILE (the '.use' help text shipped with the binary) "
          "does not exist at the path given. Only reported when the path "
          "can be resolved without guessing.")
_register("M05", "warning", "Hardcoded absolute INSTALL_ROOT_nto",
          "INSTALL_ROOT_nto is a hardcoded absolute path instead of "
          "being derived from $(PROJECT_ROOT). The build is not "
          "relocatable and will not reproduce on another machine.")
_register("M06", "warning", "Makefile includes nothing",
          "A (non top-level) Makefile contains no 'include' line at all. "
          "QNX projects normally include a common.mk that pulls in the "
          "recursive-make machinery.")
_register("M07", "warning", "USE_INSTALL_ROOT without INSTALL_ROOT_nto",
          "USE_INSTALL_ROOT is set but INSTALL_ROOT_nto is not defined "
          "in the same file, so the install root is undefined.")

# --- C sources using QNX APIs ----------------------------------------------
_register("C01", "error", "ThreadCtl without a _NTO_TCTL_* flag",
          "ThreadCtl() is called with a first argument that is not a "
          "_NTO_TCTL_* constant (e.g. _NTO_TCTL_IO). Without the right "
          "flag the call does nothing useful or fails with EPERM.")
_register("C02", "warning", "ChannelCreate with nothing connecting to it",
          "A file creates a channel (ChannelCreate) but contains no "
          "ConnectAttach() or name_attach(), so nothing in this file ever "
          "talks to the channel.")
_register("C03", "error", "resmgr_attach without a dispatch context",
          "resmgr_attach() is used but the file never creates a dispatch "
          "context (dispatch_create / dispatch_context_alloc). A resource "
          "manager cannot receive messages without one.")
_register("C04", "warning", "name_attach without name_detach",
          "name_attach() is used but the file never calls name_detach(). "
          "The name stays registered after the process exits its normal "
          "path; daemons usually detach on shutdown.")
_register("C05", "warning", "InterruptAttach without InterruptDetach",
          "InterruptAttach() / InterruptAttachEvent() is used but the "
          "file never calls InterruptDetach(). The interrupt stays "
          "attached for the lifetime of the process.")
_register("C06", "error", "ChannelCreate with a bad flags argument",
          "ChannelCreate() is called with a flags argument that is "
          "neither 0 nor a _NTO_CHF_* constant. Valid flags are 0 or a "
          "combination of _NTO_CHF_* values.")


# ---------------------------------------------------------------------------
# Findings
# ---------------------------------------------------------------------------

class Finding:
    """One reported problem."""

    def __init__(self, path, line, check_id, message):
        self.path = path
        self.line = line
        self.check_id = check_id
        self.severity = CHECKS[check_id].severity
        self.message = message

    def to_dict(self):
        return {
            "file": self.path,
            "line": self.line,
            "check": self.check_id,
            "severity": self.severity,
            "message": self.message,
        }

    def __str__(self):
        return "%s:%d: [%s %s] %s" % (
            self.path, self.line, self.check_id, self.severity, self.message)


# ---------------------------------------------------------------------------
# Text helpers
# ---------------------------------------------------------------------------

def strip_hash_comments(text):
    """Remove '#' comments (outside quotes) from mkifs/make text.

    Returns the text with comments blanked out (newlines preserved).
    """
    out = []
    i = 0
    n = len(text)
    while i < n:
        ch = text[i]
        if ch in "\"'":
            quote = ch
            out.append(ch)
            i += 1
            while i < n and text[i] != quote:
                if text[i] == "\\" and i + 1 < n:
                    out.append(text[i])
                    out.append(text[i + 1])
                    i += 2
                else:
                    out.append(text[i])
                    i += 1
            if i < n:
                out.append(text[i])
                i += 1
        elif ch == "#":
            # comment: skip to end of line, keep the newline
            while i < n and text[i] != "\n":
                i += 1
        else:
            out.append(ch)
            i += 1
    return "".join(out)


def strip_c_comments(text):
    """Remove C comments and string/char literals (newlines preserved)."""
    out = []
    i = 0
    n = len(text)
    while i < n:
        two = text[i:i + 2]
        if two == "//":
            while i < n and text[i] != "\n":
                i += 1
        elif two == "/*":
            i += 2
            while i < n and text[i:i + 2] != "*/":
                if text[i] == "\n":
                    out.append("\n")
                i += 1
            i += 2
        elif text[i] in "\"'":
            quote = text[i]
            i += 1
            while i < n and text[i] != quote:
                if text[i] == "\\" and i + 1 < n:
                    i += 2
                else:
                    if text[i] == "\n":
                        out.append("\n")
                    i += 1
            if i < n:
                i += 1
        else:
            out.append(text[i])
            i += 1
    return "".join(out)


def find_call_args(code, func_name):
    """Yield (line_number, first_argument_text) for calls to func_name.

    Works on comment-stripped code. Only the first argument is returned.
    """
    pattern = re.compile(r"\b" + re.escape(func_name) + r"\s*\(")
    for match in pattern.finditer(code):
        start = match.end()
        depth = 1
        i = start
        arg_start = start
        first_arg = None
        while i < len(code) and depth > 0:
            ch = code[i]
            if ch == "(":
                depth += 1
            elif ch == ")":
                depth -= 1
                if depth == 0:
                    first_arg = code[arg_start:i]
                    break
            elif ch == "," and depth == 1 and first_arg is None:
                first_arg = code[arg_start:i]
                break
            i += 1
        if first_arg is None:
            first_arg = code[arg_start:i]
        line = code.count("\n", 0, match.start()) + 1
        yield line, first_arg.strip()


def has_call(code, func_name):
    """True if func_name( appears in comment-stripped code."""
    return re.search(r"\b" + re.escape(func_name) + r"\s*\(", code) is not None


# ---------------------------------------------------------------------------
# mkifs .build files
# ---------------------------------------------------------------------------

# Attribute names mkifs understands inside [...].  Anything else is
# almost certainly a typo (mkifs ignores unknown attributes silently).
KNOWN_BUILD_ATTRS = {
    "image", "virtual", "uid", "gid", "perms", "type", "search", "data",
    "optional", "keeplinked", "script", "session", "raw", "compress",
    "code", "dperms", "boot", "startup", "optional", "link",
}

ATTR_RE = re.compile(r"\[([^\]]*)\]")
FILE_ENTRY_RE = re.compile(
    r"^(?:\[[^\]]*\]\s*)*(/[A-Za-z0-9_.\-][^\s=]*)\s*=\s*(.+?)\s*$")
SYMLINK_RE = re.compile(r"^\s*procmgr_symlink\s+(\S+)\s+(\S+)")


class BuildFile:
    """Parsed representation of one mkifs .build file."""

    def __init__(self, path, text):
        self.path = path
        self.raw_text = text
        self.stripped = strip_hash_comments(text)
        self.lines = self.stripped.splitlines()
        self.raw_lines = text.splitlines()
        self.sections = {}      # name -> (start_line, end_line, content)
        self.entries = []       # (line, target, source, attrs)
        self._parse()

    def _parse(self):
        """Find sections (name = { ... }) and file entries."""
        depth = 0
        current = None  # (name, start_line, [content lines])
        for lineno, line in enumerate(self.lines, 1):
            stripped = line.strip()
            # section header:  name = {   (possibly with [attrs] before it)
            m = re.match(r"^(?:\[[^\]]*\]\s*)*([A-Za-z0-9_.\-/]+)\s*=\s*\{\s*$",
                         stripped)
            if m and depth == 0:
                current = (m.group(1), lineno, [])
                depth = 1
                continue
            if current is not None:
                depth += line.count("{") - line.count("}")
                if depth <= 0:
                    name, start, content = current
                    self.sections[name] = (start, lineno, "\n".join(content))
                    current = None
                    depth = 0
                else:
                    current[2].append(line)
                continue
            depth += line.count("{") - line.count("}")
            if depth < 0:
                depth = 0
            # file entry:  /target/path = source
            m = FILE_ENTRY_RE.match(stripped)
            if m:
                attrs = ATTR_RE.findall(line)
                self.entries.append((lineno, m.group(1), m.group(2), attrs))

    def section_content(self, name):
        """Content text of a named section, or None."""
        if name in self.sections:
            return self.sections[name][2]
        return None


def check_build_file(path, text, findings, basename_index, build_dir):
    """Run the B01..B12 checks on one .build file."""
    bf = BuildFile(path, text)

    # --- B01: brace / bracket balance -------------------------------------
    depth = 0
    for lineno, line in enumerate(bf.lines, 1):
        opens = line.count("{")
        closes = line.count("}")
        depth += opens - closes
        if depth < 0:
            findings.append(Finding(
                path, lineno, "B01",
                "Unmatched '}' (brace depth went negative)."))
            depth = 0
        if line.count("[") != line.count("]"):
            findings.append(Finding(
                path, lineno, "B01",
                "Unbalanced '[' / ']' on this line."))
    if depth > 0:
        findings.append(Finding(
            path, len(bf.lines), "B01",
            "%d '{' brace(s) never closed." % depth))

    # --- B02: unknown attributes -------------------------------------------
    for lineno, line in enumerate(bf.raw_lines, 1):
        if line.lstrip().startswith("#"):
            continue
        for attr_text in ATTR_RE.findall(line):
            # 'virtual=aarch64le,raw -compress': split on commas/spaces
            for token in re.split(r"[,\s]+", attr_text.strip()):
                if not token:
                    continue
                if token.startswith(("+", "-")):
                    name = token[1:]
                elif "=" in token:
                    name = token.split("=", 1)[0]
                else:
                    name = token
                if name and name not in KNOWN_BUILD_ATTRS:
                    findings.append(Finding(
                        path, lineno, "B02",
                        "Unknown attribute '%s' in [%s]; mkifs will "
                        "ignore it." % (name, attr_text)))

    # --- B03/B04: required sections -----------------------------------------
    boot = bf.section_content("boot")
    if boot is None:
        findings.append(Finding(
            path, 1, "B03",
            "No '[virtual=...] boot = {' section found; mkifs cannot "
            "produce a bootable image."))
    script = bf.section_content("startup-script")
    if script is None:
        findings.append(Finding(
            path, 1, "B04",
            "No '[+script] startup-script = {' section found; the image "
            "would boot with no startup script."))

    # --- B05/B06: boot section contents -------------------------------------
    if boot is not None:
        if not re.search(r"\bstartup-[A-Za-z0-9_\-]+\b", boot):
            findings.append(Finding(
                path, bf.sections["boot"][0], "B05",
                "Boot section does not invoke a 'startup-<board>' "
                "binary."))
        if not re.search(r"\bprocnto(-smp)?(-instr)?\b", boot):
            findings.append(Finding(
                path, bf.sections["boot"][0], "B06",
                "Boot section does not invoke procnto; the image would "
                "contain no microkernel."))

    # --- B07/B08/B09/B10: file entries --------------------------------------
    seen_targets = {}
    for lineno, target, source, attrs in bf.entries:
        if target in seen_targets:
            findings.append(Finding(
                path, lineno, "B09",
                "Target path '%s' already listed at line %d."
                % (target, seen_targets[target])))
        else:
            seen_targets[target] = lineno
        # B10: perms / uid / gid validity
        for attr_text in attrs:
            for token in re.split(r"\s+", attr_text.strip()):
                if not token:
                    continue
                if token.startswith("perms="):
                    value = token.split("=", 1)[1]
                    if not re.fullmatch(r"[0-7]{3,4}", value):
                        findings.append(Finding(
                            path, lineno, "B10",
                            "perms value '%s' is not valid octal "
                            "(expected e.g. 0755 or 4755)." % value))
                elif token.startswith(("uid=", "gid=")):
                    value = token.split("=", 1)[1]
                    if not value.isdigit():
                        findings.append(Finding(
                            path, lineno, "B10",
                            "%s value '%s' is not numeric."
                            % (token.split("=")[0], value)))
        # B07: explicit host paths must exist
        source = source.strip()
        if source.startswith("/"):
            continue  # target-side absolute path, not a host file
        if "${" in source:
            continue  # needs QNX_TARGET / the SDP; cannot check here
        search_dirs = []
        for attr_text in attrs:
            m = re.search(r"search=([^\s\]]+)", attr_text)
            if m:
                search_dirs.extend(m.group(1).split(":"))
        if "/" in source:
            # explicit relative host path
            candidates = [os.path.join(build_dir, source)]
            candidates += [os.path.join(build_dir, d, source)
                           for d in search_dirs]
            if not any(os.path.exists(c) for c in candidates):
                findings.append(Finding(
                    path, lineno, "B07",
                    "Host file '%s' does not exist (looked in %s)."
                    % (source, build_dir)))
        else:
            # bare binary name: first try [search=] directories, then the
            # project basename index (B08)
            if search_dirs:
                if any(os.path.exists(os.path.join(build_dir, d, source))
                       for d in search_dirs):
                    continue
            if basename_index is not None and source not in basename_index:
                findings.append(Finding(
                    path, lineno, "B08",
                    "Binary '%s' not found anywhere in the scanned "
                    "project tree; it may be built by make or live in "
                    "${QNX_TARGET}." % source))

    # --- B11: procmgr_symlink ----------------------------------------------
    if script is not None:
        script_start = bf.sections["startup-script"][0]
        for offset, line in enumerate(script.splitlines()):
            m = SYMLINK_RE.match(line)
            if not m:
                continue
            src, dst = m.group(1), m.group(2)
            lineno = script_start + offset
            if not dst.startswith("/"):
                findings.append(Finding(
                    path, lineno, "B11",
                    "procmgr_symlink destination '%s' is not an "
                    "absolute path." % dst))
            if not (src.startswith(("../", "/", "${")) or
                    re.match(r"^[A-Za-z0-9_.\-/]+$", src)):
                findings.append(Finding(
                    path, lineno, "B11",
                    "procmgr_symlink source '%s' does not look like a "
                    "path." % src))

    # --- B12: inline script files need a shebang ----------------------------
    # NOTE: the shebang line itself looks like a '#' comment, so check the
    # raw (unstripped) lines of the section, not the stripped content.
    for name, (start, end, _content) in bf.sections.items():
        if name.endswith(".sh"):
            raw_content = [ln for ln in bf.raw_lines[start:end - 1]
                           if ln.strip()]
            if not raw_content or not raw_content[0].lstrip().startswith("#!"):
                findings.append(Finding(
                    path, start, "B12",
                    "Inline script '%s' has no '#!' shebang line."
                    % name))


# ---------------------------------------------------------------------------
# QNX recursive-make files
# ---------------------------------------------------------------------------

INCLUDE_RE = re.compile(r"^\s*-?\s*include\s+(.+?)\s*$")
ASSIGN_RE = re.compile(
    r"^([A-Za-z_][A-Za-z0-9_]*)\s*[:+?]?=\s*(.*?)\s*$")


def _parse_make(path, text):
    """Return (includes, assignments) for a make file.

    includes: list of (line, included-text)
    assignments: dict name -> (line, value); first assignment wins.
    """
    stripped = strip_hash_comments(text)
    includes = []
    assignments = {}
    in_conditional = False
    for lineno, line in enumerate(stripped.splitlines(), 1):
        s = line.strip()
        if not s:
            continue
        m = INCLUDE_RE.match(s)
        if m:
            includes.append((lineno, m.group(1)))
            continue
        m = ASSIGN_RE.match(s)
        if m:
            name, value = m.group(1), m.group(2)
            if name not in assignments:
                assignments[name] = (lineno, value)
    return includes, assignments


def check_make_file(path, text, findings, project_root, depth):
    """Run the M01..M07 checks on one .mk / Makefile."""
    basename = os.path.basename(path)
    includes, assigns = _parse_make(path, text)
    include_texts = [inc for _ln, inc in includes]

    def has_include(fragment):
        return any(fragment in inc for inc in include_texts)

    is_common = basename == "common.mk"

    # --- M01: QCONFIG ------------------------------------------------------
    if is_common:
        if not (has_include("$(QCONFIG)") or has_include("qconfig.mk")
                or "QCONFIG" in assigns):
            findings.append(Finding(
                path, 1, "M01",
                "common.mk never includes $(QCONFIG) and never defines "
                "QCONFIG; qconfig.mk sets up CPU/SECTION/PROJECT_ROOT."))

    # --- M02: qmacros.mk / qtargets.mk --------------------------------------
    if is_common:
        if not has_include("qmacros.mk"):
            findings.append(Finding(
                path, 1, "M02",
                "common.mk does not include "
                "$(MKFILES_ROOT)/qmacros.mk."))
        if not has_include("qtargets.mk"):
            findings.append(Finding(
                path, 1, "M02",
                "common.mk does not include "
                "$(MKFILES_ROOT)/qtargets.mk; nothing will be built."))

    # --- M03: NAME -----------------------------------------------------------
    if is_common:
        if "NAME" not in assigns:
            findings.append(Finding(
                path, 1, "M03",
                "common.mk never assigns NAME; NAME is the name of the "
                "binary or library being built."))

    # --- M04: USEFILE must exist (only when resolvable) ----------------------
    if "USEFILE" in assigns:
        lineno, value = assigns["USEFILE"]
        if "$(" not in value:
            resolved = os.path.normpath(
                os.path.join(os.path.dirname(path), value))
            if not os.path.exists(resolved):
                findings.append(Finding(
                    path, lineno, "M04",
                    "USEFILE '%s' does not exist." % value))

    # --- M05: hardcoded absolute INSTALL_ROOT_nto ---------------------------
    if "INSTALL_ROOT_nto" in assigns:
        lineno, value = assigns["INSTALL_ROOT_nto"]
        if value.startswith("/") and "$(" not in value:
            findings.append(Finding(
                path, lineno, "M05",
                "INSTALL_ROOT_nto is a hardcoded absolute path ('%s'); "
                "derive it from $(PROJECT_ROOT) so the build is "
                "relocatable." % value))

    # --- M06: Makefile includes nothing --------------------------------------
    if basename.startswith("Makefile") and depth >= 1 and not includes:
        findings.append(Finding(
            path, 1, "M06",
            "Makefile contains no 'include' line; QNX projects normally "
            "include a common.mk."))

    # --- M07: USE_INSTALL_ROOT without INSTALL_ROOT_nto -----------------------
    if "USE_INSTALL_ROOT" in assigns and "INSTALL_ROOT_nto" not in assigns:
        lineno, _value = assigns["USE_INSTALL_ROOT"]
        findings.append(Finding(
            path, lineno, "M07",
            "USE_INSTALL_ROOT is set but INSTALL_ROOT_nto is not "
            "defined in this file."))


# ---------------------------------------------------------------------------
# C sources using QNX Neutrino APIs
# ---------------------------------------------------------------------------

def check_c_file(path, text, findings):
    """Run the C01..C06 checks on one .c/.h file."""
    code = strip_c_comments(text)

    # --- C01: ThreadCtl without _NTO_TCTL_* --------------------------------
    for lineno, first_arg in find_call_args(code, "ThreadCtl"):
        if "_NTO_TCTL_" not in first_arg:
            findings.append(Finding(
                path, lineno, "C01",
                "ThreadCtl() called with first argument '%s', which is "
                "not a _NTO_TCTL_* constant." % first_arg))

    # --- C06: ChannelCreate flags -------------------------------------------
    for lineno, first_arg in find_call_args(code, "ChannelCreate"):
        arg = first_arg.strip()
        if arg != "0" and "_NTO_CHF_" not in arg:
            findings.append(Finding(
                path, lineno, "C06",
                "ChannelCreate() flags argument '%s' is neither 0 nor a "
                "_NTO_CHF_* constant." % arg))

    # --- C02: ChannelCreate with nothing connecting --------------------------
    if has_call(code, "ChannelCreate"):
        if not (has_call(code, "ConnectAttach")
                or has_call(code, "name_attach")):
            lineno = code.count("\n", 0, re.search(
                r"\bChannelCreate\s*\(", code).start()) + 1
            findings.append(Finding(
                path, lineno, "C02",
                "ChannelCreate() is used but this file never calls "
                "ConnectAttach() or name_attach(); nothing here talks "
                "to the channel."))

    # --- C03: resmgr_attach without a dispatch context -----------------------
    if has_call(code, "resmgr_attach"):
        if not (has_call(code, "dispatch_create")
                or has_call(code, "dispatch_context_alloc")):
            lineno = code.count("\n", 0, re.search(
                r"\bresmgr_attach\s*\(", code).start()) + 1
            findings.append(Finding(
                path, lineno, "C03",
                "resmgr_attach() is used but this file never creates a "
                "dispatch context (dispatch_create / "
                "dispatch_context_alloc)."))

    # --- C04: name_attach without name_detach --------------------------------
    if has_call(code, "name_attach") and not has_call(code, "name_detach"):
        lineno = code.count("\n", 0, re.search(
            r"\bname_attach\s*\(", code).start()) + 1
        findings.append(Finding(
            path, lineno, "C04",
            "name_attach() is used but this file never calls "
            "name_detach()."))

    # --- C05: InterruptAttach without InterruptDetach -------------------------
    if (has_call(code, "InterruptAttach")
            or has_call(code, "InterruptAttachEvent")):
        if not has_call(code, "InterruptDetach"):
            m = (re.search(r"\bInterruptAttachEvent\s*\(", code)
                 or re.search(r"\bInterruptAttach\s*\(", code))
            lineno = code.count("\n", 0, m.start()) + 1
            findings.append(Finding(
                path, lineno, "C05",
                "InterruptAttach[Event]() is used but this file never "
                "calls InterruptDetach()."))


# ---------------------------------------------------------------------------
# Scanning
# ---------------------------------------------------------------------------

BUILD_EXTS = (".build",)
MAKE_NAMES = ("Makefile",)
MAKE_EXTS = (".mk",)
C_EXTS = (".c", ".h")

SKIP_DIRS = {".git", ".svn", "__pycache__", "node_modules", ".hg"}


def collect_files(paths):
    """Return (files, project_roots) for the given paths.

    files: list of (path, kind) where kind is 'build', 'make' or 'c'.
    project_roots: the top-level directories that were scanned.
    """
    files = []
    roots = []
    for p in paths:
        if os.path.isfile(p):
            files.append((p, _kind_of(p)))
            roots.append(os.path.dirname(os.path.abspath(p)))
        elif os.path.isdir(p):
            roots.append(os.path.abspath(p))
            for dirpath, dirnames, filenames in os.walk(p):
                dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
                for name in filenames:
                    full = os.path.join(dirpath, name)
                    kind = _kind_of(full)
                    if kind:
                        files.append((full, kind))
        else:
            raise FileNotFoundError("no such file or directory: %s" % p)
    files.sort()
    return files, roots


def _kind_of(path):
    name = os.path.basename(path)
    if name.endswith(BUILD_EXTS):
        return "build"
    if name in MAKE_NAMES or name.startswith("Makefile."):
        return "make"
    if name.endswith(MAKE_EXTS):
        return "make"
    if name.endswith(C_EXTS):
        return "c"
    return None


def build_basename_index(roots, limit=50000):
    """Map basename -> first full path for files under the given roots."""
    index = {}
    count = 0
    for root in roots:
        for dirpath, dirnames, filenames in os.walk(root):
            dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
            for name in filenames:
                if name not in index:
                    index[name] = os.path.join(dirpath, name)
                count += 1
                if count >= limit:
                    return index
    return index


def check_path(path, kind, findings, basename_index, project_root, depth):
    """Run the checks for one file, appending to findings."""
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as fh:
            text = fh.read()
    except OSError as exc:
        findings.append(Finding(path, 0, "B01", "Cannot read file: %s" % exc))
        return
    if kind == "build":
        check_build_file(path, text, findings, basename_index,
                         os.path.dirname(path))
    elif kind == "make":
        check_make_file(path, text, findings, project_root, depth)
    elif kind == "c":
        check_c_file(path, text, findings)


# ---------------------------------------------------------------------------
# Output
# ---------------------------------------------------------------------------

def render_text(findings, files_checked, version):
    lines = ["qnxbuild-lint %s" % version, ""]
    by_file = {}
    for f in findings:
        by_file.setdefault(f.path, []).append(f)
    for path in sorted(by_file):
        lines.append(path)
        for f in sorted(by_file[path], key=lambda x: (x.line, x.check_id)):
            lines.append("  %d: [%s %s] %s"
                         % (f.line, f.check_id, f.severity, f.message))
        lines.append("")
    errors = sum(1 for f in findings if f.severity == "error")
    warnings = sum(1 for f in findings if f.severity == "warning")
    infos = sum(1 for f in findings if f.severity == "info")
    lines.append("Checked %d file(s), %d check(s) available: "
                 "%d error(s), %d warning(s), %d info"
                 % (files_checked, len(CHECKS), errors, warnings, infos))
    return "\n".join(lines)


def render_json(findings, files_checked, version):
    errors = sum(1 for f in findings if f.severity == "error")
    warnings = sum(1 for f in findings if f.severity == "warning")
    infos = sum(1 for f in findings if f.severity == "info")
    return json.dumps({
        "tool": "qnxbuild-lint",
        "version": version,
        "files_checked": files_checked,
        "checks_available": len(CHECKS),
        "summary": {"errors": errors, "warnings": warnings, "info": infos},
        "findings": [f.to_dict() for f in findings],
    }, indent=2, sort_keys=False)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def list_checks():
    out = ["qnxbuild-lint %s - %d checks"
           % (__version__, len(CHECKS)), ""]
    for check_id in sorted(CHECKS):
        c = CHECKS[check_id]
        out.append("%s [%s] %s" % (c.id, c.severity, c.title))
        out.append("    %s" % c.description)
    return "\n".join(out)


def build_parser():
    parser = argparse.ArgumentParser(
        prog="qnxbuild-lint",
        description="Static checker for QNX 8.0 project build files "
                    "(.build, common.mk/Makefile, C sources).")
    parser.add_argument("paths", nargs="*", metavar="PATH",
                        help="file or directory to check (directories are "
                             "scanned recursively)")
    parser.add_argument("--format", choices=("text", "json"), default="text",
                        help="output format (default: text)")
    parser.add_argument("--fail-on", choices=("error", "warning", "never"),
                        default="error",
                        help="fail (exit 1) when findings at this severity "
                             "or above are present (default: error)")
    parser.add_argument("--list-checks", action="store_true",
                        help="list all checks and exit")
    parser.add_argument("--version", action="version",
                        version="qnxbuild-lint " + __version__)
    return parser


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.list_checks:
        print(list_checks())
        return 0

    if not args.paths:
        parser.error("at least one PATH is required")

    try:
        files, roots = collect_files(args.paths)
    except FileNotFoundError as exc:
        print("qnxbuild-lint: %s" % exc, file=sys.stderr)
        return 2

    basename_index = build_basename_index(roots)
    findings = []
    for path, kind in files:
        rel = os.path.relpath(path, roots[0]) if roots else path
        depth = rel.count(os.sep)
        check_path(path, kind, findings, basename_index,
                   roots[0] if roots else os.path.dirname(path), depth)

    findings.sort(key=lambda f: (f.path, f.line, f.check_id))

    if args.format == "json":
        print(render_json(findings, len(files), __version__))
    else:
        print(render_text(findings, len(files), __version__))

    threshold = {"error": 2, "warning": 1, "never": 99}[args.fail_on]
    worst = max((SEVERITY_RANK[f.severity] for f in findings), default=0)
    return 1 if worst >= threshold else 0


if __name__ == "__main__":
    sys.exit(main())
