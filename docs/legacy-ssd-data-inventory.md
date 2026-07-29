# Existing SSD materials data inventory and deduplication strategy

**English** · [简体中文](legacy-ssd-data-inventory.zh-CN.md)

Updated: 2026-07-26

## 1. How it is attached

The existing directory stays where it is; nothing is copied, renamed or deleted:

```text
/home/zhilong/SSD/material_data
```

The MateriaViva data root adds a compatibility link that costs a single directory entry:

```text
data/raw/legacy-material-data -> /home/zhilong/SSD/material_data
```

Both paths sit on `/dev/nvme1n1p2`, so the unified acquisition flow can discover the existing data
without consuming a second copy of the SSD.

## 2. Measured size and formats

| Group | Measured size | Contents |
|---|---:|---|
| All existing directories | 262,116,742,634 bytes (`du` reports about 245 GiB) | 49 top-level files plus the OMat24 subtree |
| OMat24 | 201,196,941,908 bytes (about 188 GiB) | 18 training/validation/sAlex `tar.gz` archives, plus 500 extracted ASE LMDB shards and 500 lock files |
| Remaining top-level data | about 60.9 GB | 38 LMDB, 5 NPY, 5 JSON/NDJSON and 1 ZIP |

Measured entry counts for the top-level structure stores:

| File | Entries | Record form | Overlap assessment |
|---|---:|---|---|
| `mp_structs.lmdb` | 154,519 | pickled pymatgen `Structure` | Overlaps heavily with the current full MP summary, but the version and entry count differ |
| `oqmd_structs.lmdb` | 1,022,595 | pickled pymatgen `Structure` | An older structural subset of the current full OQMD v1.8 |
| `icsd_structs.lmdb` | 200,455 | pickled pymatgen `Structure` | Overlaps heavily with the 203,830 licensed local ICSD CIFs |
| `carolina_matdb_structs.lmdb` | 214,435 | pickled pymatgen `Structure` | Independent source information is insufficient; isolated as `legacy/carolina` until provenance can be recovered from the generating script or paper |
| `MP_PBE_new.json` | 74,991 rows | NDJSON, structures plus PBE properties | Overlaps MP structures; the properties and historical versions remain worth keeping |
| `OQMD_PBE_new.json` | 635,518 rows | NDJSON, structures plus PBE properties | Overlaps the main OQMD library; kept as an older property snapshot |

There are also JARVIS `cfid_3d-8-18-2021`, 84k CFID descriptors, JQE tight-binding data, structure
explanations, and training/test arrays. Among the 38 LMDBs there are both complete structure
tables and graph-converted property training sets; the latter hold `torch_geometric.data.Data`
values and must not be counted again as independent crystal sources.

## 3. Confirmed duplicate relationships

### Exact file-level duplicates

`cfid_3d-8-18-2021.json` is identical to the sole member of the ZIP with the same name:

```text
uncompressed bytes: 1,297,356,464
SHA-256: 3c778b77556ab273eb25150fa322b78f57133f7c9103684ea427b88530d2070b
```

Both the compressed and uncompressed copies are currently retained; neither is deleted without
user confirmation. Keeping only the ZIP would reclaim about 1.30 GB, and the JSON can be restored
from it losslessly.

### Heavy content overlap that is not the same file

- The old MP, OQMD, ICSD and JARVIS structure stores overlap extensively with the currently
  acquired versions, but their fields, versions and calculation methods differ, so they cannot be
  overwritten by file name or material ID.
- The old OMat24 already contains the complete training, validation and sAlex archives, but it is
  trajectory/rattled configuration data and does not enter the MateriaViva unique structure pool.
  The duplicate `omat24_1M_251210.tar.gz.part` from this round was deleted on 2026-07-26; the old
  full original files are untouched and only registered for provenance.
- `sample_*`, `train_*`, multiple splits of the same functional, and graph neural network LMDBs
  are training splits rather than new materials databases; they are ingested only as
  property/ML-artifact sidecars.

## 4. Unique properties that must not be lost

The existing directories contain properties the main structure stores do not fully cover, so they
cannot simply be deleted as "duplicate sources":

- Magnetic moments: `magmom_outcar.lmdb`, 74,261 entries.
- Elasticity: `bulk_modulus_kv.lmdb` and `shear_modulus_gv.lmdb`, 23,824 entries each.
- Thermoelectrics: n/p-type Seebeck and power factor, about 23.2k entries each.
- Band gaps and stability: PBE, PBEsol, SCAN, mBJ, GLLB-SC, OptB88 and other methods, plus mBJ hull
  data.
- Descriptors and interpretability: CFID descriptors, `explanations.npy`, `wml_test_data.npy`.
- OMat24 trajectories: AIMD, rattled, rattled-relax, validation and sAlex do not enter the unified
  structure pool and take no part in current structure/property acquisition.

## 5. Unified format and deduplication order

1. Register file-level provenance first: original path, size, modification time, inferred source,
   licence and SHA-256. Unknown sources are marked `provenance_pending`.
2. Use read-only adapters for JSON, NDJSON, pymatgen LMDB, ASE LMDB, PyG LMDB and NPY respectively;
   original files are never rewritten in place. OMat tar archives are registered for provenance
   only, with no ingestion adapter developed.
3. Convert structures into the `Crystal Record v1` extended standard layer, keeping
   `source_id/source_version/source_record_id/structure_role`.
4. Hash the normalised lattice, elements, occupancies and fractional coordinates exactly first,
   then run tolerance-based structure matching. Defects, surfaces, 2D stackings and bulk structures
   are matched separately, and trajectory frames are not collected.
5. Duplicate structures merge only the retrieval entity. Properties under different functionals,
   temperatures, pressures, magnetic states, calculation codes and experimental conditions are all
   retained as multi-valued records.
6. ICSD/CSD derivatives inherit their licence restrictions; even when they match an open structure,
   restricted original fields must not be redistributed by way of the open source.
