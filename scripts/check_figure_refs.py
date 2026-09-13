"""Every figure, panel and table is cited, and cited in reading order.

The \\PENDING* macros are defined in main.tex's preamble but expand where they
are used in body.tex, so they are substituted in before the scan.
"""
import re, sys, pathlib
ROOT = pathlib.Path("/path/to/user/workspace/matdata/paper/tex")
MAIN_ORDER = ["front_meta.tex", "front_body.tex", "body.tex", "discussion.tex", "methods.tex"]


def braced(text, i):
    d, j = 0, i
    while j < len(text):
        c = text[j]
        if c == "\\":
            j += 2; continue
        if c == "{":
            d += 1
        elif c == "}":
            d -= 1
            if d == 0:
                return text[i + 1:j], j + 1
        j += 1
    raise ValueError("unbalanced")


def macros():
    s = (ROOT / "main.tex").read_text()
    out = {}
    for m in re.finditer(r"\\newcommand\{\\(PENDING[A-Z]+)\}\{", s):
        body, _ = braced(s, m.end() - 1)
        out[m.group(1)] = body
    return out


def doc(files):
    s = "".join((ROOT / f).read_text() for f in files)
    for name, body in macros().items():
        s = s.replace("\\" + name, body)
    return s


def envs(text, kind):
    out, i = [], 0
    while True:
        i = text.find("\\begin{%s}" % kind, i)
        if i == -1:
            return out
        j = text.index("\\end{%s}" % kind, i)
        blk = text[i:j]
        m = re.search(r"\\label\{([^}]+)\}", blk)
        if m:
            out.append((m.group(1), sorted(set(re.findall(r"\\textbf\{([a-h])\},~", blk))), i))
        i = j


def cites(text, label):
    out = []
    for m in re.finditer(r"\\ref\{%s\}([a-h](?:--[a-h])?(?:,[a-h])*)?" % re.escape(label), text):
        suf, ps = m.group(1) or "", set()
        for part in suf.split(","):
            if "--" in part:
                a, b = part.split("--")
                ps |= {chr(c) for c in range(ord(a), ord(b) + 1)}
            elif part:
                ps.add(part)
        out.append((m.start(), ps))
    return out


bad = []
main_text = doc(MAIN_ORDER)
si_text = doc(["si_body.tex"])
for tag, defs_src, text, extra in (("main", "body.tex", main_text, ""),
                                   ("si", "si_body.tex", si_text, "si-")):
    src = (ROOT / defs_src).read_text()
    for kind in ("figure", "table"):
        order = []
        for lab, panels, _ in envs(src, kind):
            cs = cites(text, lab)
            if tag == "si":
                cs += cites(main_text, "si-" + lab)
            if not cs:
                bad.append(f"{tag}/{kind} {lab}: never cited"); continue
            order.append((min(c[0] for c in cs), lab))
            first = {}
            for pos, ps in sorted(cs):
                for x in ps:
                    first.setdefault(x, pos)
            miss = [x for x in panels if x not in first]
            if miss:
                bad.append(f"{tag}/{kind} {lab}: panels never cited: {miss}")
            seq = [first[x] for x in panels if x in first]
            if seq != sorted(seq):
                bad.append(f"{tag}/{kind} {lab}: panels first cited out of order")
        if order and sorted(order) != order:
            bad.append(f"{tag}/{kind}: figures first cited out of order: "
                       + str([l for _, l in sorted(order)]))
        if kind == "figure":
            print(f"{tag}: {len(envs(src, kind))} figures -> "
                  + ", ".join(l for l, _, _ in envs(src, kind)))
print()
if bad:
    print("PROBLEMS")
    for b in bad:
        print("  -", b)
    sys.exit(1)
print("all figures, panels and tables cited, and cited in order")
