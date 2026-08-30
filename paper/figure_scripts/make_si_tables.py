"""Emit the Supplementary tables straight from paper/data, so they cannot drift.

Anything a reader could check against the published database is generated here
rather than typed: the source inventory, the property registry and the cost-tier
assignment.
"""
from __future__ import annotations

import csv
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "paper" / "data"
OUT = ROOT / "paper" / "tex" / "si_tables.tex"

GROUP = {
    "general": "General-purpose DFT databases",
    "experimental": "Experimental structure catalogues",
    "specialised": "Specialised property libraries",
    "framework": "Porous and framework materials",
}
SOURCE_GROUP = {
    "alexandria": "general", "aflow": "general", "elementa": "general",
    "oqmd": "general", "gnome": "general", "materials-project": "general",
    "jarvis-qetb": "general", "matbench-discovery": "general",
    "jarvis-dft": "general", "carolina": "general", "odbx": "general",
    "mc3d": "general",
    "cod": "experimental", "icsd": "experimental",
    "hmof": "framework", "mof-carbon-capture": "framework",
    "deem-zeolites": "framework", "qmof": "framework", "mofx-db": "framework",
    "core-mof": "framework", "fair-mofs": "framework", "ec-mof": "framework",
    "curated-cof": "framework", "iza-zeolite": "framework", "pcod": "framework",
    "open-framework-aluminophosphate": "framework",
}
RESTRICTED = {"aflow", "elementa", "gnome", "icsd"}


#: pdflatex under this class drops a bare mu; the rest of the unit glyphs
#: (angstrom, superscripts, middle dot) survive as they stand.
_UNICODE = {"\u03bc": r"$\mu$", "\u00b7": r"$\cdot$"}


def esc(text: str) -> str:
    for a, b in (("&", r"\&"), ("%", r"\%"), ("_", r"\_"), ("#", r"\#")):
        text = text.replace(a, b)
    for a, b in _UNICODE.items():
        text = text.replace(a, b)
    return text


def num(value) -> str:
    return f"{int(value):,}".replace(",", "{,}")


lines: list[str] = []
add = lines.append

# ------------------------------------------------------------ S1 sources
S = list(csv.DictReader((DATA / "sources.csv").open()))
SUB = {r["source"]: r for r in csv.DictReader((DATA / "substrate_growth.csv").open())}
add(r"\begin{table}[htbp]")
add(r"\centering\footnotesize")
add(r"\caption{\textbf{The 54 integrated source databases.} Property values, "
    r"distinct properties and annotated structures are counted in the completed "
    r"database. \emph{Matched} references were resolved by identifier or "
    r"fingerprint; \emph{own} references record that the database contains the "
    r"structure as its own entry. A dagger marks the four databases whose terms "
    r"prohibit redistribution.}")
add(r"\label{tab:sources}")
add(r"\begin{tabular}{llrrrrr}")
add(r"\toprule")
add(r"Database & Licence & Values & Props & Structures & Matched & Own \\")
add(r"\midrule")
for group in ("general", "experimental", "specialised", "framework"):
    rows = [r for r in S if SOURCE_GROUP.get(r["key"], "specialised") == group]
    rows.sort(key=lambda r: -int(r["property_rows"]))
    add(rf"\multicolumn{{7}}{{l}}{{\textit{{{GROUP[group]}}}}} \\[1pt]")
    for r in rows:
        key = r["key"]
        mark = r"$^{\dagger}$" if key in RESTRICTED else ""
        matched = int(r["refs_id"]) + int(r["refs_hash"])
        add(rf"\quad \texttt{{{esc(key)}}}{mark} & {esc(r['license'][:26])} & "
            rf"{num(r['property_rows'])} & {r['n_properties']} & "
            rf"{num(r['n_materials'])} & {num(matched)} & {num(r['refs_origin'])} \\")
    add(r"\addlinespace[2pt]")
add(r"\bottomrule")
add(r"\end{tabular}")
add(r"\end{table}")
add("")

# --------------------------------------------------------- S2 properties
P = [r for r in csv.DictReader((DATA / "properties.csv").open())
     if int(r["n_materials"]) > 0]
P.sort(key=lambda r: -int(r["n_materials"]))
add(r"\begin{longtable}{lrrrr}")
add(r"\caption{\textbf{The 151 properties carrying at least one value.} Ranked "
    r"by the number of structures they cover. \emph{Sources} is the number of "
    r"databases supplying the property; \emph{shared} is the number of structures "
    r"for which two or more databases supply it, and is the subset on which "
    r"cross-database comparison is possible.}"
    r"\label{tab:properties}\\")
add(r"\toprule")
add(r"Property & Unit & Structures & Sources & Shared \\ \midrule \endfirsthead")
add(r"\multicolumn{5}{l}{\footnotesize\itshape Table \ref{tab:properties}, "
    r"continued}\\ \toprule")
add(r"Property & Unit & Structures & Sources & Shared \\ \midrule \endhead")
add(r"\bottomrule \endfoot")
for r in P:
    unit = esc(r["unit"]) if r["unit"] else "--"
    add(rf"\texttt{{{esc(r['property'])}}} & {unit} & {num(r['n_materials'])} & "
        rf"{r['n_sources']} & {num(r['n_materials_multi_source'])} \\")
add(r"\end{longtable}")
add("")

# --------------------------------------------------------- S3 cost tiers
T = list(csv.DictReader((DATA / "cost_tiers.csv").open()))
TJ = json.loads((DATA / "cost_tiers.json").read_text())
add(r"\begin{table}[htbp]")
add(r"\centering\footnotesize")
add(r"\caption{\textbf{Assignment of the 69 general-purpose properties to "
    r"calculation tiers.} The assignment is a hand judgement about what a "
    r"property costs to obtain and is listed in full so that it can be disputed "
    r"item by item. Properties whose domain is a single material family are "
    r"excluded.}")
add(r"\label{tab:tiers}")
add(r"\begin{tabular}{p{0.30\textwidth}p{0.62\textwidth}}")
add(r"\toprule")
add(r"Tier & Properties \\")
add(r"\midrule")
for tier in (1, 2, 3, 4):
    names = [r["property"] for r in T if int(r["tier"]) == tier]
    label = TJ[str(tier)]["label"]
    med = TJ[str(tier)]["median_coverage"] * 100
    joined = ", ".join(rf"\texttt{{{esc(n)}}}" for n in names)
    add(rf"\textbf{{{tier}}} {esc(label)} \newline median coverage {med:.3g}\% & "
        rf"{joined} \\")
    add(r"\addlinespace[3pt]")
add(r"\bottomrule")
add(r"\end{tabular}")
add(r"\end{table}")
add("")

# ------------------------------------------------- S4 agreement pair table
A = list(csv.DictReader((DATA / "agreement_pairs.csv").open()))
A.sort(key=lambda r: (r["property"], -int(r["n_shared"])))
add(r"\begin{longtable}{llrrrrr}")
add(r"\caption{\textbf{Pairwise agreement between databases.} Every pair of "
    r"databases sharing at least 200 structures for a comparable property. "
    r"$\Delta$ is the difference between the two databases in the order listed. "
    r"A median signed difference close to the median absolute difference "
    r"indicates that nearly all of the disagreement carries one sign.}"
    r"\label{tab:pairs}\\")
add(r"\toprule")
add(r"Property & Pair & Shared & med.\ $\Delta$ & med.\ $|\Delta|$ & "
    r"within tol. & $r$ \\ \midrule \endfirsthead")
add(r"\multicolumn{7}{l}{\footnotesize\itshape Table \ref{tab:pairs}, "
    r"continued}\\ \toprule")
add(r"Property & Pair & Shared & med.\ $\Delta$ & med.\ $|\Delta|$ & "
    r"within tol. & $r$ \\ \midrule \endhead")
add(r"\bottomrule \endfoot")
for r in A:
    add(rf"\texttt{{{esc(r['property'])}}} & "
        rf"\texttt{{{esc(r['source_a'])}}}\,/\,\texttt{{{esc(r['source_b'])}}} & "
        rf"{num(r['n_shared'])} & {float(r['median_signed_diff']):+.4g} & "
        rf"{float(r['median_abs_diff']):.4g} & "
        rf"{float(r['frac_within_tol'])*100:.1f}\% & "
        rf"{float(r['pearson_r']):.3f} \\")
add(r"\end{longtable}")

OUT.write_text("\n".join(lines) + "\n", encoding="utf-8")
print(f"wrote {OUT} ({len(lines)} lines, {len(S)} sources, {len(P)} properties, "
      f"{len(A)} pairs)")
