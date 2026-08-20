"""Deem hypothetical zeolites (SLC-refined "good" subset, database 2.1).

Three tgz archives of ~330k PCOD CIF files (plus simulated-XRD .txt files,
skipped). Each CIF is streamed straight out of the tar as verbatim text; the
PCOD id is the native id and nothing in the pool references these ids, so no
match_ids. The zeolite family label comes from SOURCE_FAMILY in the registry.

The commented-out GULP trailer
------------------------------
Every file ends with the output of the SLC-forcefield GULP run that produced
it, written as CIF comments so that no CIF parser ever sees it::

    # Total GULP energy -198415.050123 kJ/mol
    # GULP energy per Si atom -12400.940633 kJ/mol
    # Density = 2.243430 g / cm^3
    # Si number density = 22.485475 Si / 1000 Ang^3
    ...
    # Convention : Reuss Voigt Hill
    # Bulk Modulus (GPa) = 56.21126 58.01805 57.11465

That trailer is the entire property payload of this database, so it is parsed
out of the raw text here. Skipped on purpose: the 6x6 elastic constant and
compliance matrices (tensors, and the pool stores scalars); the
"Compressibility (1/GPa)" line, which is exactly 1 / bulk_modulus_reuss and
would only restate it; and the "Total GULP energy" line, which is per unit cell
and so not comparable between frameworks -- only its per-Si normalisation is.

Method strings
--------------
Base method is "GULP SLC forcefield". The Reuss/Voigt/Hill bulk and shear
moduli separate by property name already, so they share the bare base method.
Everything that would otherwise collide on (material, property) carries the
discriminator in its method instead:

* ``youngs_modulus`` -- three values, one per stress axis, so the method names
  the axis ("... (stress axis x)").
* ``poisson_ratio`` -- six directional values, emitted as six rows tagged with
  the tensor component ("... (ν_yx)") rather than as one averaged row. The
  arithmetic mean of six directional Poisson ratios is not the isotropic ratio
  of anything: for the anisotropic frameworks that dominate this set it is a
  number with no physical referent, and averaging would discard exactly the
  anisotropy a hypothetical-zeolite screen is looking for. A consumer wanting
  one number can derive the isotropic ratio from the Hill bulk and shear
  moduli, both of which are stored. Mind the transpose when reading the
  trailer: GULP labels each line with the *strain* axis and its columns with
  the stress axes, so "Poissons Ratio (x)" carries ν_yx and ν_zx.
* ``sound_velocity_*`` -- GULP prints Reuss/Voigt/Hill triples here too, but
  the canonical vocabulary has one name per polarisation, so only the Hill
  value is emitted and the method says so.
* the two dielectric constants are isotropic averages of the printed 3x3
  tensors, and their methods say "trace/3" so the averaging is never silent.

``energy_per_t_atom`` is a new name
-----------------------------------
The GULP energy per Si atom is the ranking quantity of this database, but it is
a forcefield lattice energy per *tetrahedral* atom in kJ/mol -- not a DFT total
energy per atom in eV/atom -- so putting it in ``total_energy_per_atom`` would
corrupt that column. It is emitted as ``energy_per_t_atom`` (kJ/mol), following
the T-atom convention the registry already uses for ``framework_density`` and
reusable by any other framework source reporting the same quantity. The loader
registers unknown names on the fly with the unit passed here; registry.py still
wants the permanent entry.

Diverged elastic values are dropped
-----------------------------------
Deem ran GULP over every framework unattended, including frameworks whose
elastic compliance matrix is near-singular, and the Reuss/Voigt averages then
blow up or change sign in the raw file: 8063636 is published with a Reuss shear
modulus of 249421.58 GPa and an S-wave velocity of 363.6 km/s, 8039830 with a
Voigt bulk modulus of -0.40 GPa. Those are numerical artefacts of the source's
own averaging, not soft frameworks, and a plausibility window per name keeps
them out of the pool (counted and printed at the end of the run, as in the
materials-project and elementa adapters). The windows for names those adapters
already guard are copied from them verbatim, so one convention holds pool-wide.
The geometric outputs -- density, framework density, energy per T atom -- cannot
diverge this way and are passed through unguarded. Over the full 331,172 files
the guard drops 30,393 of 7,285,781 values, 0.42%.

How incomplete the trailers are
-------------------------------
Barely: all twelve lines read here are present in all 331,172 files. What does
go wrong is field overflow -- GULP prints a run of '*' where a number no longer
fits its column -- in exactly one file for the shear moduli (8163621, whose
line reads ``= ************* 27.81331 *************``) and in six files for the
compressibility, which is not read anyway. That single overflow is why every
multi-value line is required to yield its full count of numbers: the one number
left standing in 8163621 is the Voigt modulus, and a parser that took what it
could get would file it as the Reuss one.
"""

from __future__ import annotations

import re
import tarfile
from collections import Counter
from typing import Iterator

from scripts.properties.adapters._util import safe_float
from scripts.properties.base import PropertyValue, SourceAdapter, SourceRecord

_ARCHIVES = (
    "database_2.1_slc_good_1_of_3.tgz",
    "database_2.1_slc_good_2_of_3.tgz",
    "database_2.1_slc_good_3_of_3.tgz",
)

_METHOD = "GULP SLC forcefield"
_HILL_METHOD = f"{_METHOD} (Hill average)"

#: forcefield lattice energy per tetrahedral atom; see the module docstring for
#: why this is not total_energy_per_atom. Needs an entry in registry.py.
_ENERGY_PROPERTY = "energy_per_t_atom"

#: the order GULP prints under "Convention : Reuss Voigt Hill"; Hill IS the VRH
#: average, hence the third suffix
_BOUNDS = ("reuss", "voigt", "vrh")

#: plausibility windows for the values GULP's averaging can diverge on. The
#: moduli and sound velocities repeat the materials-project windows; the
#: Poisson window is wide enough for genuinely auxetic and strongly anisotropic
#: frameworks (isotropy would cap it at 0.5) while still catching divergence,
#: and a diagonal-averaged dielectric constant below 1 is unphysical.
_RANGES: dict[str, tuple[float, float]] = {
    "bulk_modulus_reuss": (0.0, 2_000.0),
    "bulk_modulus_voigt": (0.0, 2_000.0),
    "bulk_modulus_vrh": (0.0, 2_000.0),
    "shear_modulus_reuss": (0.0, 2_000.0),
    "shear_modulus_voigt": (0.0, 2_000.0),
    "shear_modulus_vrh": (0.0, 2_000.0),
    "sound_velocity_transverse": (0.0, 30_000.0),
    "sound_velocity_longitudinal": (0.0, 30_000.0),
    "youngs_modulus": (0.0, 2_000.0),
    "poisson_ratio": (-5.0, 5.0),
    "dielectric_constant_total": (1.0, 1_000.0),
    "dielectric_constant_electronic": (1.0, 1_000.0),
}

_NUMBER = r"[-+]?(?:\d+\.?\d*|\.\d+)(?:[eE][-+]?\d+)?"
_RE_NUMBER = re.compile(_NUMBER)

# Every pattern is line-anchored on the comment marker and spells inner
# whitespace [ \t] rather than \s, so a truncated trailer can never let one
# line's match run on into the next.
_RE_BULK = re.compile(r"^#[ \t]*Bulk Modulus \(GPa\)[ \t]*=(.*)$", re.M)
_RE_SHEAR = re.compile(r"^#[ \t]*Shear Modulus \(GPa\)[ \t]*=(.*)$", re.M)
_RE_S_WAVE = re.compile(r"^#[ \t]*Velocity S-wave \(km/s\)[ \t]*=(.*)$", re.M)
_RE_P_WAVE = re.compile(r"^#[ \t]*Velocity P-wave \(km/s\)[ \t]*=(.*)$", re.M)
_RE_YOUNGS = re.compile(r"^#[ \t]*Youngs Moduli \(GPa\)[ \t]*=(.*)$", re.M)
_RE_POISSON = re.compile(r"^#[ \t]*Poissons Ratio \(([xyz])\)[ \t]*=(.*)$", re.M)
_RE_DENSITY = re.compile(
    r"^#[ \t]*Density[ \t]*=[ \t]*(" + _NUMBER + r")[ \t]*g[ \t]*/[ \t]*cm\^3", re.M
)
_RE_SI_DENSITY = re.compile(
    r"^#[ \t]*Si number density[ \t]*=[ \t]*(" + _NUMBER + r")", re.M
)
_RE_FRAMEWORK_DENSITY = re.compile(
    r"^#[ \t]*_framework density[ \t]+(" + _NUMBER + r")", re.M
)
_RE_ENERGY_PER_SI = re.compile(
    r"^#[ \t]*GULP energy per Si atom[ \t]+(" + _NUMBER + r")[ \t]*kJ/mol", re.M
)
_RE_STATIC_TENSOR = re.compile(r"^#[ \t]*Static dielectric constant tensor:", re.M)
_RE_HIGH_FREQ_TENSOR = re.compile(
    r"^#[ \t]*High freq\. dielectric constant tensor:", re.M
)
#: "#    x 4.682590 -1.194570 0.742060"; the elastic matrices label their rows
#: with digits instead, so they can never be picked up here
_RE_TENSOR_ROW = re.compile(r"^#[ \t]+([xyz])((?:[ \t]+" + _NUMBER + r"){3})[ \t]*$")
#: the "#      x y z" column heading GULP prints between header and first row
_RE_TENSOR_AXES = re.compile(r"^#[ \t]+x[ \t]+y[ \t]+z[ \t]*$")


def _floats(chunk: str, expected: int) -> list[float] | None:
    """The ``expected`` numbers in ``chunk``, or None if the count is wrong.

    A count mismatch returns None instead of a short list because every value
    parsed here is positional (Reuss/Voigt/Hill, x/y/z): once one token has
    failed to parse -- GULP prints a field of '*' when a number overflows its
    width -- the survivors can no longer be assigned to the right name.
    """

    values = [safe_float(token) for token in _RE_NUMBER.findall(chunk)]
    numbers = [value for value in values if value is not None]
    return numbers if len(numbers) == expected else None


def _scalar(pattern: re.Pattern[str], text: str) -> float | None:
    """The single number captured by ``pattern``, or None if absent/unusable."""

    match = pattern.search(text)
    return safe_float(match.group(1)) if match else None


def _row(pattern: re.Pattern[str], text: str, expected: int) -> list[float] | None:
    """The numbers on the first line matching ``pattern``, or None."""

    match = pattern.search(text)
    return _floats(match.group(1), expected) if match else None


def _tensor_diagonal_mean(pattern: re.Pattern[str], text: str) -> float | None:
    """Isotropic average (trace / 3) of the 3x3 tensor printed under a header.

    The x, y and z rows have to follow the header immediately and in that
    order; anything else yields nothing. Scanning ahead for the next three
    [xyz]-labelled rows instead would be unsafe here, because the two
    dielectric tensors are printed four lines apart: a static block missing a
    row would then be completed with high-frequency rows and averaged into a
    number that looks like a dielectric constant but is two tensors mixed.
    """

    header = pattern.search(text)
    if header is None:
        return None
    diagonal: list[float] = []
    # the header's own line ends at header.end(), so element 0 is its tail
    for line in text[header.end() :].split("\n")[1:5]:
        line = line.rstrip("\r")
        if not diagonal and _RE_TENSOR_AXES.match(line):
            continue  # the "x y z" column heading
        row = _RE_TENSOR_ROW.match(line)
        if row is None or row.group(1) != "xyz"[len(diagonal)]:
            return None
        values = _floats(row.group(2), 3)
        if values is None:
            return None
        diagonal.append(values[len(diagonal)])
        if len(diagonal) == 3:
            return sum(diagonal) / 3.0
    return None


class DeemZeolitesAdapter(SourceAdapter):
    source_key = "deem-zeolites"
    always_hash = False
    properties_only = False

    def __init__(self, root=None) -> None:
        super().__init__(root)
        self.drops: Counter[str] = Counter()

    def _guard(self, value: float | None, name: str) -> float | None:
        """Drop (and count) values outside the window declared for `name`."""

        window = _RANGES.get(name)
        if value is None or window is None:
            return value
        if not (window[0] <= value <= window[1]):
            self.drops[name] += 1
            return None
        return value

    def _trailer_properties(self, text: str) -> list[PropertyValue]:
        """Scalar properties from the commented-out GULP trailer of one CIF.

        Every field is independently optional: a missing, truncated or
        overflowed line costs only its own properties, never the record, and no
        input can raise out of here.
        """

        properties: list[PropertyValue] = []

        for pattern, prefix in (
            (_RE_BULK, "bulk_modulus"),
            (_RE_SHEAR, "shear_modulus"),
        ):
            moduli = _row(pattern, text, 3)
            if moduli is None:
                continue
            for bound, modulus in zip(_BOUNDS, moduli):
                name = f"{prefix}_{bound}"
                value = self._guard(modulus, name)
                if value is not None:
                    properties.append(PropertyValue(name, value, "GPa", _METHOD))

        for pattern, name in (
            (_RE_S_WAVE, "sound_velocity_transverse"),
            (_RE_P_WAVE, "sound_velocity_longitudinal"),
        ):
            velocities = _row(pattern, text, 3)
            if velocities is None:
                continue
            value = self._guard(velocities[2] * 1000.0, name)  # km/s -> m/s, Hill
            if value is not None:
                properties.append(PropertyValue(name, value, "m/s", _HILL_METHOD))

        youngs = _row(_RE_YOUNGS, text, 3)
        if youngs is not None:
            for axis, modulus in zip("xyz", youngs):
                value = self._guard(modulus, "youngs_modulus")
                if value is not None:
                    properties.append(
                        PropertyValue(
                            "youngs_modulus",
                            value,
                            "GPa",
                            f"{_METHOD} (stress axis {axis})",
                        )
                    )

        # The label in "Poissons Ratio (x) = a b" is the *strain* axis, not the
        # loaded one. The columns are the stress axes named by the "Stress axis"
        # heading above, minus the blank diagonal, so the line reads ν_yx and
        # ν_zx in the ν_ij = -ε_j/ε_i convention -- the transpose of what the
        # label suggests. Checked against the compliance matrix printed a few
        # lines earlier in the same trailer: a = -S_xy/S_yy = ν_yx exactly, and
        # only this reading satisfies reciprocity, ν_xy/ν_yx = E_x/E_y, against
        # the Youngs moduli of the same file.
        seen_axes: set[str] = set()
        for match in _RE_POISSON.finditer(text):
            axis = match.group(1)
            if axis in seen_axes:
                continue  # first line per axis only, as for every other field
            seen_axes.add(axis)
            ratios = _floats(match.group(2), 2)
            if ratios is None:
                continue
            stress_axes = [other for other in "xyz" if other != axis]
            for stress, ratio in zip(stress_axes, ratios):
                value = self._guard(ratio, "poisson_ratio")
                if value is not None:
                    method = f"{_METHOD} (ν_{stress}{axis})"
                    properties.append(
                        PropertyValue("poisson_ratio", value, None, method)
                    )

        density = _scalar(_RE_DENSITY, text)
        if density is not None:
            properties.append(PropertyValue("density", density, "g/cm³", _METHOD))

        # "Si number density" and the "# _framework density" line print the same
        # T-atoms-per-1000-Å³ number, so either spelling on its own is enough.
        framework_density = _scalar(_RE_SI_DENSITY, text)
        if framework_density is None:
            framework_density = _scalar(_RE_FRAMEWORK_DENSITY, text)
        if framework_density is not None:
            properties.append(
                PropertyValue(
                    "framework_density", framework_density, "T/1000 Å³", _METHOD
                )
            )

        energy = _scalar(_RE_ENERGY_PER_SI, text)
        if energy is not None:
            properties.append(
                PropertyValue(_ENERGY_PROPERTY, energy, "kJ/mol", _METHOD)
            )

        for pattern, name, label in (
            (_RE_STATIC_TENSOR, "dielectric_constant_total", "static"),
            (_RE_HIGH_FREQ_TENSOR, "dielectric_constant_electronic", "high-frequency"),
        ):
            value = self._guard(_tensor_diagonal_mean(pattern, text), name)
            if value is not None:
                properties.append(
                    PropertyValue(
                        name, value, None, f"{_METHOD} ({label} tensor trace/3)"
                    )
                )

        return properties

    def iter_records(self, limit: int | None = None) -> Iterator[SourceRecord]:
        count = 0
        try:
            for archive in _ARCHIVES:
                path = self.root / archive
                with tarfile.open(path, mode="r|gz") as bundle:
                    for member in bundle:
                        if not member.isfile() or not member.name.endswith(".cif"):
                            continue
                        if limit is not None and count >= limit:
                            return
                        handle = bundle.extractfile(member)
                        if handle is None:
                            continue
                        cif_text = handle.read().decode("utf-8", errors="replace")
                        pcodid = member.name.rsplit("/", 1)[-1][: -len(".cif")]
                        count += 1
                        yield SourceRecord(
                            native_id=f"pcod-{pcodid}",
                            properties=self._trailer_properties(cif_text),
                            structure=cif_text,
                        )
        finally:
            print(
                "[deem-zeolites] value drops: "
                + (str(dict(self.drops)) if self.drops else "none"),
                flush=True,
            )
