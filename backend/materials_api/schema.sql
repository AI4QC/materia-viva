PRAGMA journal_mode = WAL;
PRAGMA synchronous = NORMAL;
PRAGMA temp_store = MEMORY;
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS materials (
    pk INTEGER PRIMARY KEY,
    material_id TEXT NOT NULL UNIQUE,
    formula TEXT NOT NULL,
    chemical_system TEXT NOT NULL,
    dataset TEXT NOT NULL CHECK (dataset IN ('experimental', 'candidate')),
    is_experimental INTEGER NOT NULL CHECK (is_experimental IN (0, 1)),
    source_split TEXT NOT NULL,
    source_index TEXT NOT NULL,
    n_elements INTEGER NOT NULL,
    n_atoms REAL NOT NULL,
    pbes_gap REAL,
    density REAL,
    volume REAL,
    spacegroup_number INTEGER,
    spacegroup_symbol TEXT,
    crystal_system TEXT,
    lattice_a REAL,
    lattice_b REAL,
    lattice_c REAL,
    lattice_alpha REAL,
    lattice_beta REAL,
    lattice_gamma REAL,
    formation_energy_per_atom REAL,
    energy_above_hull REAL,
    is_stable INTEGER,
    is_metal INTEGER,
    magnetic_ordering TEXT,
    total_magnetization REAL,
    bulk_modulus REAL,
    shear_modulus REAL,
    poisson_ratio REAL,
    blob_offset INTEGER NOT NULL,
    blob_length INTEGER NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS material_elements (
    material_pk INTEGER NOT NULL REFERENCES materials(pk) ON DELETE CASCADE,
    element TEXT NOT NULL,
    PRIMARY KEY (material_pk, element)
) WITHOUT ROWID;

CREATE TABLE IF NOT EXISTS metadata (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
) WITHOUT ROWID;

CREATE INDEX IF NOT EXISTS idx_materials_dataset ON materials(dataset, pk);
CREATE INDEX IF NOT EXISTS idx_materials_formula ON materials(formula COLLATE NOCASE, pk);
CREATE INDEX IF NOT EXISTS idx_materials_chemsys ON materials(chemical_system, pk);
CREATE INDEX IF NOT EXISTS idx_materials_gap ON materials(pbes_gap, pk) WHERE pbes_gap IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_materials_density ON materials(density, pk) WHERE density IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_materials_n_atoms ON materials(n_atoms, pk);
CREATE INDEX IF NOT EXISTS idx_materials_n_elements ON materials(n_elements, pk);
CREATE INDEX IF NOT EXISTS idx_materials_spacegroup ON materials(spacegroup_number, pk)
    WHERE spacegroup_number IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_materials_crystal_system ON materials(crystal_system, pk)
    WHERE crystal_system IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_materials_volume ON materials(volume, pk) WHERE volume IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_materials_formation_energy ON materials(formation_energy_per_atom, pk)
    WHERE formation_energy_per_atom IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_materials_e_hull ON materials(energy_above_hull, pk)
    WHERE energy_above_hull IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_materials_stability ON materials(is_stable, pk) WHERE is_stable IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_materials_metallicity ON materials(is_metal, pk) WHERE is_metal IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_elements_element_material ON material_elements(element, material_pk);
