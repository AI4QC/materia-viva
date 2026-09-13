"""One colour system for the five figures.

The problem it solves: before this, database families, cost tiers and property
identities each borrowed from the same handful of hues, so the same blue meant
"general-purpose DFT" in one panel, "tier 1" in the next and "band gap" in a
third. A reader cannot carry a legend across panels when the hue is reused for
unrelated things.

The system has four parts, and nothing outside them should be introduced:

  1. ACCENT      one blue for the corpus, our model, and the "after" state;
                 one amber for the mechanism that makes the corpus grow.
  2. NEUTRALS    everything that is context rather than subject.
  3. CATEGORICAL disjoint sets, one per kind of thing being distinguished.
                 A hue is never shared between two of these sets.
  4. SEQUENTIAL  ordered quantities: cost tier (cool to warm = cheap to dear),
                 and the two continuous ramps.

Import names rather than literals, so a change here reaches all five figures.
"""
from __future__ import annotations

from matplotlib.colors import LinearSegmentedColormap

# --------------------------------------------------------------- 1  accent
ACCENT      = "#1B5E8C"   # the corpus, our model, the state after integration
ACCENT_SOFT = "#5FA8D3"   # the same thing, secondary weight
MECHANISM   = "#D9822B"   # admission, the growing substrate, "what was added"

# ------------------------------------------------------------- 2  neutrals
INK   = "#24282A"
SOFT  = "#6B7074"
MID   = "#A8AEB2"
LIGHT = "#D4D8DA"
PALE  = "#EEF1F2"

# ---------------------------------------------------------- 3  categorical
#: the four families a source database belongs to
FAMILY = {
    "general":      "#1B5E8C",
    "experimental": "#B5462F",
    "specialised":  "#2E7D5B",
    "framework":    "#D9A13A",
}
FAMILY_LABEL = {
    "general":      "General-purpose DFT",
    "experimental": "Experimental catalogues",
    "specialised":  "Specialised property libraries",
    "framework":    "Porous and framework materials",
}

#: how a cross-database reference was resolved
ROUTE = {"id": "#2E7D5B", "hash": "#5FA8D3", "origin": "#D9A13A"}

#: the eight properties that can be compared between databases
PROPERTY = {
    "band_gap":                  "#1B5E8C",
    "formation_energy_per_atom": "#2E7D5B",
    "energy_above_hull":         "#5FA8D3",
    "total_magnetization":       "#8A6BA8",
    "bulk_modulus_vrh":          "#D9A13A",
    "shear_modulus_vrh":         "#B5462F",
    "density":                   "#8C6239",
    "volume_per_atom":           "#9AA0A4",
}

#: identity criteria, in order of strictness
CRITERION = ["#2E7D5B", "#1B5E8C", "#D9822B", "#B5462F"]

#: a long categorical run (applicability domains); starts from the family hues
#: and then moves away from them so no two adjacent bars are confusable
LONG = ["#1B5E8C", "#D9A13A", "#2E7D5B", "#5FA8D3", "#8A6BA8", "#B5462F",
        "#8C6239", "#9AA0A4", "#C3CBCE", "#6E9E8A"]

# ----------------------------------------------------------- 4  sequential
#: cost tier: cool is cheap, warm is dear, and the four steps stay ordered in
#: greyscale as well as in colour
TIER = {1: "#2F6E9E", 2: "#3E9AA8", 3: "#8FB04B", 4: "#D98E2B"}

#: shared crystals between two databases
SHARED = LinearSegmentedColormap.from_list(
    "shared", ["#EEF4F8", "#5FA8D3", "#1B5E8C", "#0A2E4A"])

#: fraction of a pair agreeing within tolerance
AGREE = LinearSegmentedColormap.from_list(
    "agree", ["#B5462F", "#E0C877", "#2E7D5B"])

#: degree of the spherical harmonic, in the architecture panel
ELL = LinearSegmentedColormap.from_list("ell", ["#BBD6E8", "#1B5E8C", "#0A2E4A"])

# ------------------------------------------------- compatibility aliases
# The draft scripts were written against style.py's names. Re-pointing the
# aliases here is what makes one edit reach every panel.
BLU = ACCENT
CYA = ACCENT_SOFT
GRN = FAMILY["specialised"]
ORA = FAMILY["framework"]
RED = FAMILY["experimental"]
PUR = PROPERTY["total_magnetization"]
GRY = SOFT
LGY = LIGHT
