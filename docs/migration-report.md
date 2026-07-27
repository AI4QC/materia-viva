# Migration report — 2026-07-26

## Result

CMU application code was moved from the former nested web directory into the
standalone `/home/zhilong/workspace/matdata` Git repository. Active database files
were moved to `/home/zhilong/SSD/workspace_data/matdata/data` on the secondary NVMe
SSD. Repository and legacy paths resolve to this single active data tree.

## Migrated assets

| Asset | Approximate size | New location | Integrity gate |
|---|---:|---|---|
| Experimental source | 283 MB | `data/sources/experimental` | source/destination SHA-256 plus full record validation |
| Candidate source | 7.1 GB | `data/sources/candidate` | same-filesystem inode-preserving move plus full record validation |
| Search index | 5.6 GB | `data/index` | source/destination SHA-256 and clean SQLite/API reads |
| External provenance sources | 30 GB | `data/raw/external_structs` | SHA-256 for all 1,071 files |
| Extracted ICSD CIFs | 1.1 GB, 203,830 files | `data/raw/icsd_extracted` | source/destination SHA-256 for every file |
| Original ICSD archive | 635 MB | `data/raw/ICSD_data.zip` | source/destination SHA-256 |

The source CSV validation produced these released counts:

- Experimental: 94,204 train + 4,958 validation = 99,162.
- Candidate: 5,814,133 train + 306,007 validation = 6,120,140.
- Combined searchable index: 6,219,302 records.

## Compatibility and recovery

Legacy application, source-dataset, and raw-data paths were replaced by symbolic
links after their targets passed the integrity gates. Cross-filesystem source
directories were moved to the desktop trash rather than irreversibly erased, so
they remain recoverable until that trash is emptied. The candidate dataset was an
inode-preserving rename within the secondary SSD and has no duplicate active copy.
