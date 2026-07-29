# Crystal structure and property database acquisition notes

**English** · [简体中文](dataset-acquisition.zh-CN.md)

Updated: 2026-07-28

This file records MateriaViva's coverage of external crystal databases, actual download status,
licence boundaries and required manual steps. The machine-readable catalog lives at
[`scripts/datasets/sources.json`](../scripts/datasets/sources.json).

"Coverage" here is not the same as "already downloaded". The catalog currently registers exactly
**101 sources**: 61 source paths already exist on this machine, of which 55 sit under
`data/raw/acquired/`, 5 reuse existing data in `data/raw/external_structs/`, and the licensed ICSD
sits in `data/raw/icsd_extracted/`. The remaining 40 have no local source path yet, for reasons
including account or paid licences, no official bulk interface, provider prohibitions on bulk
download, and trajectories excluded by project scope. The true state of each entry is whatever the
catalog's `status` and `data_path` say; a source-discovery count must never be read as a
download-completion count.

Split by catalog status: 58 acquired or reusing existing data, 18 registered only or awaiting an
official bulk route, 22 requiring a user account, provider authorization or a paid licence, and 3
trajectory sources excluded by scope. There are no unfinished background downloads. The four groups
total 101 sources.

## 1. Storage and format conventions

All database files — including `.part` resume files, API pages, archives, receipts and later
normalisation results — live only under:

```text
/home/zhilong/SSD/workspace_data/materia-viva/data
```

`data` in the repository is a symlink to that directory. The downloader keeps at least 50 GiB free
by default; target files are written as `.part` first and atomically renamed once the byte count
checks out. Retries for large files are driven by an outer Python layer starting a new curl
process; each curl process disables its internal retry and resumes from the current real byte
offset of the `.part` file, which prevents an internal retry from reopening and truncating the file
after an SSL interruption. Every completed static file has a `*.receipt.json` beside it recording
the source URL, byte count, SHA-256 and completion time.

The download layer preserves each source's original format, which is required for auditing and
rebuilding. Raw JSON, SQL, LMDB, CIF, ASE DB and similar files never enter the website index
directly. Two conversion layers run before anything enters MateriaViva:

1. Structure master records convert to `Crystal Record v1`, whose core fields are
   `index, material_id, cif, pbes_gap`.
2. Source-specific properties are written to a provenance/property sidecar, then into unified
   SQLite property columns or JSON extension fields. Units are converted in the adapter, while the
   original value, original unit, source ID and version are always retained.

So "the raw archive formats differ" does not mean "the published database formats differ". The
website and downstream programs read only the normalised layer and must never read `data/raw`
directly.

## 2. Data already present, not downloaded again

| Database | Local contents | Current status | Licence / notes |
|---|---:|---|---|
| [COD](https://wiki.crystallography.net/howtoobtaincod) | 533,486 records, about 30.4 GB of Parquet | Complete snapshot present | CC0; rsync is also officially supported. |
| ICSD | 203,830 CIFs | User-provided licensed copy present | Commercially licensed data; local use only, never re-fetched automatically or redistributed. |
| Materials Project experimental-origin | 49,235 records | Present | The full MP summary is downloaded separately this round. |
| AFLOW-ICSD derived subset | 60,386 records | Present | AFLOW academic / non-commercial terms. |
| [MC3D](https://archive.materialscloud.org/record/2025.139) | CIF/metadata archives across several versions | Present | Full provenance of the latest archive totals about 95.4 GiB; structure-level data is already local, so the full provenance is not pulled again. |
| [QMOF](https://github.com/Andrew-S-Rosen/QMOF) | 20k+ QMOF | Present | CC BY 4.0. |
| [CoRE MOF](https://zenodo.org/communities/coremof/) | Several release archives | Present | Version licences are stored with the Zenodo record. |
| [Curated COFs](https://github.com/lipelopesoliveira/curatedCOFs) | 984 CIFs | Present | Repository version and source retained. |

These directories live under `data/raw/external_structs/`. Existing copies are not decompressed and
rewritten for the sake of uniformity; unification happens in the derived index layer so that the
original evidence is not lost.

## 3. Open data acquired automatically this round

| Database | Official scale / scope this round | Local target | Status and method |
|---|---:|---|---|
| [Materials Project](https://docs.materialsproject.org/downloading-data/how-do-i-download-the-materials-project-database) | 154,377 summary documents measured through the current API | `raw/acquired/materials-project/summary-2026-07-26/` | Uses the local `MP_API_KEY`, one gzip page per 1,000 records; includes structures plus the energy, stability, band gap, magnetism, elasticity and dielectric fields in the summary. |
| [OQMD v1.8](https://oqmd.org/download/) | 21,034,479,961 byte SQL gzip; released 2026-02 | `raw/acquired/oqmd/` | Official full-database archive, CC BY 4.0; only the archive is stored, not yet imported, as the official estimate needs about another 100 GB. |
| [AFLOW](https://aflow.org/documentation/) | 2,981,853 records measured through AFLUX | `raw/acquired/aflow/` | Two acquisition paths: the 400k property snapshot from JARVIS/Figshare, and full AFLUX structure+property paging. The latter requests geometry, fractional positions, species, formation enthalpy, band gap, density and more. |
| [Alexandria](https://alexandria.icams.rub.de/datasets.html) | PBE 3D about 5M, 2D about 200k, 1D about 100k; plus PBEsol/SCAN at about 500k each | `raw/acquired/alexandria/` | Mirrors the official 2025.07.02 PBE shards plus PBE-2D, PBE-1D, PBEsol and SCAN; about 4.3 GB compressed. |
| [Alexandria JARVIS repack](https://figshare.com/articles/dataset/27174897) | A 2024.10.1 snapshot of the same kind of data | `raw/acquired/alexandria-jarvis-snapshot/` | The 1.4 GB NIST JARVIS repack is downloaded too, as a complete usable backup when the official shards are slow; deduplicated by version at ingestion. |
| [GNoME](https://github.com/google-deepmind/materials_discovery/blob/main/DATASET.md) | About 381k new stable structures | `raw/acquired/gnome/` | Downloads `by_id.zip`, the main property table and the r2SCAN table; CC BY-NC 4.0. |
| [NIST JARVIS-DFT](https://pages.nist.gov/jarvis/databases/) | 2025 edition 3D structures/properties | `raw/acquired/jarvis-dft/` | Downloads the latest 2025 JSON ZIP from Figshare. |
| [C2DB / 2DHub](https://2dhub.org/) | JARVIS snapshot, 3,514 records | `raw/acquired/c2db/` | Downloaded through the public NIST JARVIS Figshare mirror; 2DHub also offers online properties and an API. |
| [2DMatPedia](https://www.2dmatpedia.org/download) | About 6k records | `raw/acquired/2dmatpedia/` | The official site currently has unstable TLS/availability, so the public NIST JARVIS Figshare mirror is used. |
| [OMDB-GAP1](https://omdb.mathub.io/dataset/) | 12,500 organic crystals | `raw/acquired/omdb/` | The official download redirects to a login page; the official login route is attempted while also downloading the public NIST JARVIS/Figshare mirror. |
| [hMOF](https://figshare.com/articles/dataset/15127758) | 137,651 hypothetical MOFs | `raw/acquired/hmof/` | Figshare JSON ZIP. |
| [SNUMAT](https://figshare.com/articles/dataset/21713885) | About 10k hybrid-functional records | `raw/acquired/snumat/` | Figshare JSON ZIP. |
| [MC2D](https://archive.materialscloud.org/record/2022.84) | 3,077 exfoliated and 2,710 optimised structures | `raw/acquired/mc2d/` | Exfoliated structures, optimised structures and `structure_2d.json` downloaded; the 8.4 GiB full AiiDA provenance is not. |
| [3DSC](https://github.com/aimat-lab/3DSC) | 3DSC-MP 5,759 records with superconducting critical temperatures | `raw/acquired/3dsc/` | Code and open data downloaded; the ICSD-restricted portion carries only ICSD IDs, no redistributable structures. |
| [MatterGen data release](https://github.com/microsoft/mattergen) | MP-20 about 45k; Alex-MP-20 about 600k | `raw/acquired/mattergen/` | Downloads the two training-set ZIPs from Git LFS. |
| [MPtrj](https://figshare.com/articles/dataset/23713842) | About 1.58M structure trajectories, 12.19 GB | Not acquired | Relaxation trajectory data rather than unique material structures; excluded from the download queue. |
| [Matbench Discovery / WBM](https://figshare.com/articles/dataset/Matbench_Discovery_v1_0_0/22715158) | WBM 256,963 candidate structures | `raw/acquired/matbench-discovery/` | Downloads the MP snapshot, WBM initial/relaxed structures, combined entries and summary. |
| [OMat24](https://huggingface.co/datasets/facebook/OMAT24) | 100,824,585 configurations in the full training set | Old SSD data registered only, not ingested into MateriaViva | Trajectory/rattled configuration data; the existing roughly 188 GiB of original files stay untouched but are excluded from unique-structure acquisition and unified ingestion. |
| [ELEMENTA / ELEMENTA Spin](https://huggingface.co/datasets/kairosmaterial/ELEMENTA) | 43,521,713 frames across 2,235,193 relaxations | `raw/acquired/elementa/` | Trajectory data ingested endpoint-only: 2,005,836 unique final structures merged into the candidate pool. CC BY-NC 4.0. See section 4. |

### 3.1 Actual download status snapshot

The following reflects on-disk state at 2026-07-26 22:05 CDT. All paths sit under the SSD data root.

- Materials Project summary completed 154,377 / 154,377 records; all 155 gzip pages passed decode
  checks and the manifest reads `complete: true`.
- Downloaded and verified by byte count, SHA-256, compressed stream, SQLite quick check or paging
  manifest: GNoME, JARVIS-DFT and its specialized static endpoints, C2DB, 2DMatPedia, the OMDB
  mirror, hMOF, SNUMAT, MC2D, 3DSC, MatterGen, Matbench/WBM, all official Alexandria PBE/PBEsol/SCAN
  shards, ODBX 137,909 records, Materials Cloud static OPTIMADE 43,478 records, HADB 165 static
  endpoints, CCP-NC 5,804 Magres, MAD 95,595 records, the ShiftML2 static portion, OBELiX, the
  324,426-record MOF carbon-capture set, HEX 457 high-pressure CIFs, HOFSyn 631 raw and 631 P1
  CIFs, 312 open-framework aluminophosphate CIFs, SPSE 91,763 static structures, opXRD 92,552
  experimental patterns (912 complete structures), B‑IncStrDB 282 msCIFs, FAIR-MOF, MOFX, MOSAEC,
  the Phonix summary, NovoMag, TopoMat, BiDB, 2D-alloys, Deem zeolites, ARC-MOF, CMR's 27 periodic
  ASE DBs, RRUFF and the AFLOW prototype library.
- SACADA yielded 1,644 static structure archives; 17 further numbered official ZIPs in the catalog
  return 404 and are recorded as unavailable rather than padded with fabricated structures.
- AFLOW AFLUX completed 2,981,853 / 2,981,853 records; TCOD completed 7,499 / 7,499 final CIFs;
  SuperBand's 13,292,718,528 byte HDF5 completed and passed an HDF5 open check, with 2,474 materials
  at the root level. EC-MOF yielded 1,071 complete structure/property pairs, the sole missing entry
  `ZnHTTX_Bulk` returning 404 from the official structure endpoint.
- OQMD and SIMPOD recovered from 18,565,977,758 and 33,863,725,056 bytes respectively after the
  retry logic was fixed, completing at 21,034,479,961 bytes of SQL gzip and 47,781,765,915 bytes of
  `Structures.zip`. The downloader atomically removed the `.part` suffix and wrote SHA-256 receipts;
  OQMD passed a full-stream `gzip -t`, and SIMPOD passed full extraction and CRC verification of
  467,861 entries using a Python Zip64 reader. Resumption used `--retry 0 --continue-at -` and never
  truncated existing bytes.
- MPtrj and OMat24 are both excluded under the "collect unique structures only, not trajectories"
  scope; two unfinished `.part` files were deleted on 2026-07-26, freeing about 6.1 GB. The existing
  `/home/zhilong/SSD/material_data/OMAT24` originals stay untouched but never enter the MateriaViva
  unified structure pool.
- Files in flight keep the `.part` suffix; a `*.receipt.json` appears only after byte-count
  verification and the atomic rename. API data counts as complete only when the manifest satisfies
  both `complete: true` and downloaded count equal to total count.

To check status live:

```bash
cd /home/zhilong/workspace/materia-viva
find data/raw/acquired -type f -name '*.part' -printf '%p\t%s bytes\n'
jq '{downloaded_documents,total_documents,complete,updated_at}' \
  data/raw/acquired/materials-project/summary-2026-07-26/manifest.json \
  data/raw/acquired/aflow/aflux-2026-07-26/manifest.json
find data/raw/acquired -type f -name '*.receipt.json' | sort
```

### 3.2 Second-round expansion sources

The machine-readable catalog now contains 101 sources. The following were added in the second round
as specialized structure/property libraries:

| Source | Scale / contents | Automation status | Overlap handling |
|---|---|---|---|
| [FAIR-MOFs](https://zenodo.org/records/13254307) | 45,699 experimental and 33,361 optimised MOFs, plus synthesis conditions, porosity, formation energy, topology and ligand/metal clusters | CC BY 4.0, 10 release files downloaded and verified | Structure-matched against CoRE/CSD-derived MOFs; synthesis conditions kept as property/provenance sidecars |
| [MOFX-DB](https://mof.tech.northwestern.edu/databases) | CIFs from CoREMOF, hMOF, IZA, PCOD-syn and ToBaCCo plus 3 million adsorption data points | Six official bulk ZIPs downloaded and verified | CIFs deduplicated against existing MOF/zeolite structures; gas isotherms retained |
| [MOSAEC-DB](https://zenodo.org/records/15808197) | Chemical validity, descriptors and subsets for about 124k experimental MOFs | 5 open descriptor files downloaded and verified | Original CIFs come from CSD and need a CSD licence; open descriptors are never mistaken for redistributable structures |
| [Phonix](https://phonix-db.org/) | About 20k target materials and 6,800+ thermal conductivity results; the summary carries structures, phonon DOS and thermal transport | 156 MB Parquet summary downloaded; the full force-constant tar set far exceeds current space limits | Joined to MP by MP ID and structural fingerprint, never counted again as new materials |
| [NovoMag](https://www.novomag.physics.iastate.edu/structure-database) | 3,826 rare-earth-free magnetic materials plus supplementary Fe-Co-Zr structures | Two CC BY 4.0 official Zenodo packages downloaded and verified | Magnetic anisotropy and magnetic provenance retained |
| [TopoMat](https://www.materialscloud.org/discover/topomat) | Band structures and topological indices for 13,628 structures, 4.02 GB | Materials Cloud bulk tar downloaded and verified | Structures originate from ICSD/COD; adds topological properties only, not experimental material counts |
| [BiDB](https://www.2dhub.org/bidb/bidb.html) / [2D-alloys](https://www.2dhub.org/2dalloys/2dalloys.html) | 8,451 bilayer stackings and 400 two-dimensional alloys | Two official ASE DBs downloaded and verified | 2D monolayers, bilayers, heterostructures and bulk use distinct `structure_role` values |
| [SACADA](https://www.sacada.info/) | Official metadata currently lists 1,661 curated 3D carbon allotropes with density, band gap, relative energy, bulk modulus and hardness | 1,644 official CIF ZIPs downloaded; 17 numbers have no ZIP on the site | Missing entries recorded explicitly as unavailable, never counted as acquired structures |
| [Deem hypothetical zeolites](https://mwdeem.org/PCOD/index.html) | The v2.1 `slc/good` subset holds 331k unique zeolite-like structures | Three CC BY 4.0 bulk packages downloaded and verified | Deduplicated later against zeolite structures in PCOD, IZA and MOFX |
| [ARC-MOF](https://zenodo.org/records/7600474) | About 280k experimental or computed MOFs with REPEAT charges, geometric/RAC/RDF descriptors and adsorption properties | All 24 CC BY 4.0 structure, charge, descriptor and adsorption files downloaded; 4 tar.gz passed stream checks | Structures and properties retained in full first; overlap with hMOF, CoRE, FAIR-MOF and MOFX handled later |
| [NIST JARVIS specialized datasets](https://pages.nist.gov/jarvis/databases/) | 1.1k 2D materials, vacancy/surface/interface, crystalline polymers, MXene, superconductors and AGRA/TinNet catalysis endpoints | 16 official Figshare ZIPs downloaded and verified | Only static structure endpoints and their properties are collected; OCP, ALIGNN-FF, M3GNet-MPF and other duplicate/force-field training configurations are explicitly skipped |
| [AMCSD / RRUFF](https://www.rruff.net/about/download-data/) | Mineral CIF/AMC files, diffraction records, plus microprobe, Raman, infrared and powder XRD properties | 16 full structure/property ZIPs downloaded and verified | AMCSD CIFs are the structural entity; RRUFF spectra/chemistry/diffraction become multi-valued properties of the same mineral, matched against COD later |
| [MPOD](https://mpod.cimav.edu.mx/) | Experimental tensor properties of crystalline materials in CIF/STAR-style `.mpod` files linked to structure information | Registered; the site supports per-record files but no stable bulk endpoint was found this round | An experimental tensor property overlay that never double-counts the same COD structure |
| [EC-MOF Phase-I](https://ec-mof.njit.edu/) | The official selector covers 1,072 bulk/monolayer candidates; the paper reports 1,061 valid structures | 1,071 static CIF/property pairs acquired; `ZnHTTX_Bulk` returns 404 and is kept explicitly in the manifest | Bulk and monolayer labelled separately; missing candidates are never fabricated and no optimization trajectories are downloaded |
| [AFLOW Prototype Encyclopedia](https://aflowlib.duke.edu/p/index.html) | 2,050 canonical crystal structure prototypes covering all space groups | Apache-2.0 official prototype definition repository downloaded and verified | Prototypes are structure-type references, never added to real material entries; used for later prototype classification |
| [QPOD](https://www.2dhub.org/qpod/qpod.html) / [HetDB](https://www.2dhub.org/hetdb/hetdb.html) / [X2DB](https://www.2dhub.org/x2db/x2db.html) | 2D defects, heterostructures and experimental 2D material metadata | Official browsing/API available, but current documentation lists no stable bulk file | No page scraping; awaiting an official bulk/API cursor export route |
| [PCOD](https://www.crystallography.net/pcod/) | 1,062,771 public-domain predicted CIFs | The official rsync endpoint was confirmed listable | A million small files are not scattered onto NTFS directly; a resumable tar/index streaming route is being designed first |
| [MAGNDATA](https://cryst.ehu.es/magndata/) / [IZA](https://www.iza-structure.org/databases/) | 2,000+ magnetic structures and approved zeolite frameworks | Both officially support per-record `.mcif` / CIF, with no clearly documented bulk endpoint | No high-frequency page scraping; IZA's open structures and adsorption snapshot are covered by the MOFX-DB packages |
| [Catalysis-Hub](https://www.catalysis-hub.org/) | Surface reactions, adsorption structures, energies and calculation parameters | The official GraphQL API is registered, to be exported by publication/dataset paging | Slabs, adsorbates and transition states are never merged with bulk crystals |

### 3.3 Third-round expansion sources

The third round focused on large federated interfaces, specialized static structure libraries and
datasets that easily mix in trajectories. The strategy is to preserve each source as-is with full
properties and provenance, deferring format conversion and cross-database structural deduplication.

| Source | Scale / contents | Current status | Scope note |
|---|---:|---|---|
| [ODBX](https://odbx.science/) | 56 records in the main library, 137,853 in misc, with formation energies and hull distances | 137,909 / 137,909 OPTIMADE static structures downloaded, paging manifest complete | Deduplicated later against structure prediction libraries, keeping ODBX-specific properties |
| [Materials Cloud OPTIMADE](https://optimade.materialscloud.org/) | 3,079 records across 5 specialized libraries, 40,399 across 4 Archive static libraries | 43,478 downloaded in full, keeping provider default full fields for source-specific properties | The 4,396,695 Li-ion records in `jk-9v` are mostly MD frames and are explicitly excluded |
| [TCOD](https://www.crystallography.net/tcod/) | 7,499 final theoretical CIFs | Low-rate resumable download from the official directory tree | Final CIFs only, no calculation-process trajectories |
| [HADB](https://hadb.funmat-ii.se/) | 244 hard-coating entries | 165 DFT/MLIP static endpoints downloaded; 79 AIMD entries excluded | CIFs retained together with the web property table and page hashes |
| [CCP-NC Magres](https://www.ccpnc.ac.uk/database/) | 5,804 latest crystal records with NMR shielding/EFG | 3,212 PDDL and 2,592 CC BY records downloaded in chunks and verified | Only the latest static `.magres` version of each immutable record is kept |
| [CMR static periodic libraries](https://cmr.fysik.dtu.dk/) | 27 ASE DBs covering low-dimensional, surface, adsorption, perovskite and OQMD-derived data | 27 / 27 periodic ASE SQLite DBs downloaded, each passing `PRAGMA quick_check`; non-periodic molecule, dye and nanoparticle libraries excluded | The C1DB page still exists, but the official `c1db.db` currently returns 404 |
| [MAD static](https://archive.materialscloud.org/records/c4ene-0mv14) | 95,595 periodic static structures with energies and train/test/val labels | train/test/val, subset metadata and atomic energies downloaded and verified | The MPtrj benchmark and large AiiDA provenance archives are not downloaded |
| [ShiftML2](https://archive.materialscloud.org/records/j2fka-sda13) | Molecular crystal training/test sets, an experimental NMR benchmark and polymorphs | The static portion downloaded and verified | `relax_vs_md.zip` is a trajectory comparison package and is explicitly excluded |
| [OBELiX](https://github.com/NRC-Mila/OBELiX) | 599 synthesised solid electrolytes, 321 with complete CIFs | Full CSV and the complete CIF tar downloaded and verified | Experimental room-temperature ionic conductivity, DOI, approximate-structure flags and ICSD IDs retained |
| [MOF carbon capture](https://archive.materialscloud.org/record/2018.0016/v3) | 324,426 hypothetical MOFs with partial charges and CO₂/N₂ adsorption properties | The CC BY 4.0 1.2 GiB structure package, 55.5 MiB property package and experimental structures downloaded and passing tar/ZIP checks | Overlap with hMOF, ARC-MOF and MOFX deduplicated later |
| [HEX high-pressure structures](https://springernature.figshare.com/collections/HEX_a_complete_Database_of_High-Pressure_Elemental_Crystal_Structures/7119778/1) | Ground states and structure-search candidates for the first 57 elements at 0, 100, 200 and 300 GPa | CC0; official ZIP downloaded, MD5 matching and passing ZIP checks; 457 genuine CIFs after excluding macOS resource forks | The same element at different pressures or as different candidates is retained separately first, then deduplicated by structural fingerprint |
| [HPCSD](https://www.calypso.cn/) | 77,346 static high-pressure structures in the first release, covering 89 elements | The portal requires login and the paper notes that more data must be requested; registered without scraping authenticated pages | After registering and requesting bulk, only static structures are collected, never structure-search trajectories |
| [Matterverse](https://optimade.matterverse.ai/) | 31,791,192 hypothetical materials measured | OPTIMADE verified, but capped at 500 per page with no full-database file; an unbounded mirror of about 63,583 requests was not started | Collect after requesting a bulk snapshot from the provider |
| [MOF DB ML](https://mofdb.org/) | H2MOF-ML 4,034 records, hMOF-ML 137,953 records | The official Hugging Face repository currently returns 401 | Download after logging in and confirming token/licence; hMOF deduplicated against the local copy later |
| [ADAQ](https://defects.anyterial.se/) | 47,403 defects, 79 hosts | Complete or substantial replication needs provider permission | Contact the provider first; do not bypass the authorization boundary by scraping |
| [AMDB](https://altermagnets.anyterial.se/) | 180 altermagnet property records | Registered, structures link to MAGNDATA, no bulk found | A property overlay on MAGNDATA that does not double-count structures |
| [NLR MatDB](https://materials.nlr.gov/) | Relaxed structures, stability, GW, dielectric and effective mass for renewable-energy materials | Supports interactive query/CSV, no complete bulk structure endpoint found | A full-database export must be requested from NLR |
| [NIMS AtomWork open](https://crystdb.nims.go.jp/en/) | Officially lists 82,000 open structures, 55,000 properties and 15,000 phase diagrams | Requires DICE registration and a MatNavi application; the site explicitly prohibits scraping | Use the official export after user registration, never scrape |
| [MatGen](https://matgen.nscc-gz.cn/index_ch.html) | Inorganic, hypothetical, 2D, superconductor, solid-electrolyte, porous and ABACUS libraries | The API documentation entry currently 404s; registration or contacting `matgen@nscc-gz.cn` required | Collect static structures after requesting bulk/API; molten-salt MD is out of scope |
| [MatCloud+](https://www.matcloud.com.cn/newDataBase/structure) | Several structure and property libraries | A JavaScript search page with no public redistributable bulk endpoint | Request an account-level export from the provider after registering |
| [Atomly](https://atomly.net/) | The site advertises about 349,043 compounds | The official frontend states the API is for internal testing and collaborators only; contact `atomly@iphy.ac.cn` | The site certificate had expired when checked on 2026-07-26; no insecure automated mirroring |
| [MatCraft](https://matcraft.ai/docs/materials-api/overview) | Documentation claims 205,000+ records, mainly sourced from MP, AFLOW and JARVIS | 100 guest requests per hour, details require per-record structure fetches, terms prohibit over-limit bulk; the API TLS handshake failed in testing | These upstreams are already local; decide on mirroring only after obtaining provider bulk authorization |
| [2D hybrid perovskites](https://arxiv.org/abs/2006.14302) | 515 experimental 2D hybrid perovskites with CIFs, band gaps and predicted charges | The paper's database site is HTTP-only with no bulk package under a clear redistribution licence | Contact the authors for a secure full-database package and licence |
| [OpenMX AB₂ 2D map](https://www.openmx-square.org/2d-ab2/) | 3,844 AB₂ two-dimensional candidates | Interactive per-record access, no bulk archive found | Request the bulk file rather than scraping page by page |
| [MPDD](https://providers.optimade.org/index-metadbs/mpdd) | Structure/descriptor database | The registry sub-endpoint is currently HTTP-only and unavailable | Contact Phases Research Lab for the current HTTPS/bulk address |

### 3.4 Fourth-round static structure and diffraction/electronic property sources

This round extended to organic frameworks, minerals, modulated crystals, experimental/simulated
powder diffraction and superconductor electronic structure. Raw packages are preserved per source in
full, but only static structure endpoints become structure records; diffraction, band structure and
transport data are attached as properties, and NEB/migration path coordinates are never converted
into crystal records.

| Source | Scale / contents | Current status | Unique-structure boundary |
|---|---:|---|---|
| [HOFSyn](https://figshare.com/articles/dataset/HOFSyn/28856483) | 660 synthesis-table records, two structure packages of 631 real CIFs each | CSV, raw CIFs and P1-normalised CIFs downloaded and passing ZIP checks | The raw/P1 versions of one HOF keep their source relationship first, then deduplicate by fingerprint; the 2.35 GB literature PDF package is not downloaded |
| [Open-framework AlPO](https://figshare.com/articles/dataset/Database_of_Open-Framework_Aluminophosphate_Structures/7822574) | 312 experimental open-framework aluminophosphates with topology and simulated XRD | 312 CIFs and the XLSX property table downloaded and fully extractable | Each published structure is one static endpoint; XRD is a property and generates no extra structures |
| [opXRD](https://zenodo.org/records/15298026) | 92,552 experimental powder patterns; 2,179 with structure labels, of which 912 are complete structures and 1,267 partial | The 1.40 GB official ZIP downloaded and passing a full ZIP check; per-record parsed counts match the published scale | Only the 912 labels with a lattice and complete atomic basis enter the structure layer; partial labels and remaining patterns are experimental property data producing no structures |
| [SIMPOD](https://doi.org/10.57760/sciencedb.09755) | 467,861 static COD structures with simulated 1D powder diffraction | The 47,781,765,915 byte `Structures.zip` completed, with a SHA-256 receipt and full Zip64 CRC verification | COD overlap is not removed yet; the main package carrying structures and 1D diffraction is downloaded while the 29.4 GB derived images and two redundant CSV exports are excluded. Older Info-ZIP 6.00 misjudges this oversized Zip64 file, so verify with Python `zipfile` |
| [SPSE](https://figshare.com/articles/dataset/High-Throughput_Screening_Platform_for_Solid_Electrolytes_Combining_Hierarchical_Ion-Transport_Prediction_Algorithms_/12011412) | 91,763 static structures plus BVSE/CAVD/conduction descriptors | The data ZIP and README downloaded and verified; in practice 6 NDJSON tables | The 91,763 records in `cifs.json` enter the candidate structure layer; the `paths` coordinate arrays in 49 hierarchical records are explicitly excluded, treated as neither trajectory frames nor structures |
| [SuperBand](https://github.com/ljcj007/SuperBand) | Structures, band structures and Fermi surfaces for 2,474 superconductors | The 13.29 GB official HDF5 and a code snapshot both completed and verified | Structures come mainly from MP/OQMD; SuperBand's specific electronic properties are retained first, then joined by structure rather than double-counted |
| [NIMS PhononDB](https://mdr.nims.go.jp/collections/8g84ms862?locale=en) | Harmonic phonons, DOS and thermodynamic properties for 10,034 static MP materials | CC BY 4.0; per-record datasets are open but there is no collection-level bulk file, so a full package has been requested | Each MP ID produces exactly one static structure record; displacement supercells in `phonopy_params.yaml.xz` serve only as phonon property inputs and generate no extra structures |
| [B-IncStrDB](https://cryst.ehu.es/bincstrdb/) | 282 modulated or composite crystals, including 47 composite entries | 282 / 282 official msCIFs downloaded; 29 index pages, 282 receipts and per-file SHA‑256 all verified | One published msCIF per database ID; no JSmol images, animations or trajectories |
| [MinCryst](https://database.iem.ac.ru/mincryst/) / [Webmineral](https://webmineral.com/) | The IUCr catalog records 5,000+ mineral phases each; Webmineral has 4,714 descriptive entries | The MinCryst official host is currently unreachable; Webmineral has no clear bulk atomic-coordinate export | No interactive page scraping; awaiting provider recovery or bulk authorization |
| [PowBase](https://www.cristal.org/powbase/index.html) | 169 CIF/powder pattern ZIPs | The site explicitly asks mirrors to contact the maintainer, so it is registered without bulk fetching | Collect static structures/patterns after mirroring permission, never by brute-forcing a number sequence |
| [NIST Crystal Data](https://www.nist.gov/publications/nist-3-nist-crystal-data) / [NIST Surface Structure Database](https://www.nist.gov/publications/nist-42-nist-surface-structure-database-version-30) | 237,671 crystal records; nearly 1,400 experimental surface structures | Both are NIST SRD licensed/legacy products requiring purchase or contact with NIST | Import final structures after obtaining an institutional licence, never copy around the licence |

The 245 GiB of existing data in `/home/zhilong/SSD/material_data` is registered through the
`data/raw/legacy-material-data` symlink without copying. Exact file-level duplicates, content-level
overlap for MP/OQMD/ICSD/JARVIS, property retention rules and the OMat24 exclusion are described in
[`legacy-ssd-data-inventory.md`](legacy-ssd-data-inventory.md).

"Full" for Materials Project here means all material-level `SummaryDoc` records from the current
main API, not an indiscriminate copy of raw VASP tasks, build intermediates, images and every user
attachment. The legacy parsed/build objects on [MP AWS Open
Data](https://docs.materialsproject.org/downloading-data/aws-opendata) already amount to about
55.9 GB, with roughly another 58 GB of structure images; these overlap heavily with material-level
structure/property search and are not downloaded this round. MPContribs additionally holds public,
private and differently licensed data maintained per project; the official recommendation is to call
`download_contributions()` per project through `mpcontribs-client`. This round collects unique
structure projects such as QMOF separately, explicitly excludes trajectory projects such as MPtrj,
and neither downloads private projects without authorization nor mixes per-project attachments into
main-database data.

All download commands are re-runnable: completed files are skipped and unfinished ones resume from
`.part`:

```bash
cd /home/zhilong/workspace/materia-viva

# list all sources
PYTHONPATH=. python scripts/datasets/acquire.py --list

# static archives; --source may repeat
PYTHONPATH=. python scripts/datasets/acquire.py \
  --source oqmd --source alexandria --source gnome

# full MP summary API
MP_API_KEY='your-key' PYTHONPATH=. \
  python scripts/datasets/materials_project.py

# full AFLOW AFLUX; 10,000 records per page
PYTHONPATH=. python scripts/datasets/aflow.py --page-size 10000

# SACADA unique carbon structures; automatically skips completed entries and officially missing ZIPs
PYTHONPATH=. python scripts/datasets/sacada.py --delay 0.25

# EC-MOF bulk/monolayer structure endpoints and matching properties
PYTHONPATH=. python scripts/datasets/ec_mof.py --delay 0.25

# generic OPTIMADE static structure export, e.g. ODBX; gzip per page, resumable
PYTHONPATH=. python scripts/datasets/optimade_export.py --provider odbx-misc

# TCOD final CIFs, HADB static endpoints, CCP-NC latest Magres
PYTHONPATH=. python scripts/datasets/tcod.py --request-delay 0.02
PYTHONPATH=. python scripts/datasets/hadb.py --request-delay 0.1
PYTHONPATH=. python scripts/datasets/ccpnc_magres.py --chunk-size 250 --request-delay 0.1

# B-IncStrDB: one published msCIF per ID
PYTHONPATH=. python scripts/datasets/bincstrdb.py --request-delay 0.1

# OBELiX, MOF carbon-capture and other official static bulk files
PYTHONPATH=. python scripts/datasets/acquire.py \
  --source obelix --source mof-carbon-capture --source hex-high-pressure \
  --source hofsyn --source open-framework-aluminophosphate --source spse
```

To keep keys out of shell history, set them in a `.env` outside Git or in the current shell first;
the scripts read only from environment variables, and neither receipts nor manifests store keys.

## 4. Probed but not mirrored without bounds

### NOMAD

The [NOMAD API](https://nomad-lab.eu/prod/v1/docs/howto/manage/program/download.html) currently
returns 19,393,938 entries for an empty query. Public data usually needs no token, but each upload
may carry a different licence, and raw files, archive and entry form one-to-many/multi-version
relationships. Blindly writing every raw calculation to disk would far exceed the remaining SSD
capacity.

Define a subset first — for example only data containing canonical crystal structures, a given code
or a given elemental system. The official API can stream raw ZIP or archive:

```bash
curl -X POST 'https://nomad-lab.eu/prod/v1/api/v1/entries/query' \
  -H 'Content-Type: application/json' \
  -d '{"query":{},"pagination":{"page_size":1}}'
```

For private/embargoed data, obtain a token from the NOMAD user page and set `NOMAD_TOKEN`. This
machine has no such token, which does not affect public data queries.

### OPTIMADE federation

The [OPTIMADE provider registry](https://providers.optimade.org/providers.json) currently lists 29
providers. OPTIMADE is a cross-database unified query layer, not a standalone database that can be
downloaded in one go, and many of its providers are already acquired separately in this table.
Cursors should be stored as provider ID + structure ID so that MP, OQMD, Alexandria and NOMAD are
not mirrored repeatedly.

### OMat24, MPtrj, Open Catalyst and other trajectory libraries

This data consists mainly of relaxation, rattled, molecular-dynamics or reaction-path intermediate
configurations of the same system. It does not match MateriaViva's current "unique material
structure + matching properties" scope, so it is not downloaded, not converted and not counted in
the unified structure pool. The existing full OMat24 archive on the old SSD keeps only its original
files and provenance registration and takes no part in ingestion. For databases that publish both
initial and final relaxed structures, both endpoints may be kept and labelled with `structure_role`;
intermediate trajectory frames are always excluded, and whether the two endpoints are structurally
equivalent is left to the later unified fingerprint deduplication stage.

### ELEMENTA and ELEMENTA Spin

[ELEMENTA](https://huggingface.co/datasets/kairosmaterial/ELEMENTA)
([paper](https://www.kairosmaterials.com/papers/ELEMENTA.pdf)) is also trajectory data, but it
supplies explicit trajectory boundaries and convergence information on a "one endpoint per
relaxation" basis, so it is ingested under the endpoint rule above: only the last ionic step of each
optimization trajectory is taken and every intermediate frame is discarded. The core archive holds
38,808,603 frames across 2,028,008 relaxations and the spin archive 4,713,110 frames across 207,185
relaxations, for 2,235,193 endpoints in total.

Trajectory identity is the `(material, structure, spin)` triple, not the `material` field alone. The
two archives are not labelled consistently: the core archive and the head of the spin archive encode
the magnetic state inside `material` (`Cl2V_01_spin_00`) and carry a separate `spin` field, while
the rest of the spin archive reuses one `material` per composition (`Al12Mn4Y4_01`) and distinguishes
runs only through `structure` (`Al12Mn4Y4_01_mag24`), with no `spin` field at all. Grouping by
`material` alone merges adjacent magnetic relaxations into one and loses about 62% of the spin
archive's trajectories. The extraction script also treats an `ionic_step` reset as a fallback
trajectory boundary.

ELEMENTA Spin runs several magnetic initializations of the same geometry, and those relaxation
endpoints share a BAWL fingerprint; deduplication keeps the lowest-energy one as representative and
merges the rest as duplicate structures. ELEMENTA labels only total energy, forces, stress and
magnetic moment, with no PBEsol band gap, so ingested rows leave `pbes_gap` empty.

The licence is CC BY-NC 4.0, stricter than CC BY, so after ingestion the whole public snapshot is
released under non-commercial terms; see the copyright and redistribution boundary in the README.

## 5. Requiring user action or restricted by licence

### MPDS / Pauling File

Entry points: [MPDS API documentation](https://developer.mpds.io/); data browsing and accounts:
[MPDS](https://mpds.io/).

This machine has no `MPDS_API_KEY`. You need to:

1. Log in to or apply for an MPDS/Pauling File account with API access.
2. Copy the API key from the account page.
3. Run `export MPDS_API_KEY='...'` in the terminal; never paste the key into chat or commit it.
4. Tell me to continue; I will first call the official facet/download API to check licence and quota,
   then download in resumable shards.

### CSD / CCDC

Entry points: [CSD conditions of
use](https://downloads.ccdc.cam.ac.uk/documentation/API/conditions_of_use.html), [Access
Structures](https://www.ccdc.cam.ac.uk/structures/).

The full CSD and the CSD Python API require a valid institutional/commercial licence and cannot be
bulk-downloaded or redistributed without one. Access Structures can retrieve individual published
deposited CIFs by known DOI, CCDC deposition number or refcode, but it is not an unrestricted
full-database interface. Confirm whether this machine already has a CSD installation and
institutional licence; with a licence, export through the official CCDC API into
`raw/acquired/csd/`.

### ICSD

Entry points: [ICSD official site](https://icsd.products.fiz-karlsruhe.de/en), [API licence
conditions](https://icsd.products.fiz-karlsruhe.de/sites/default/files/ICSD/documents/terms/ICSD_API_License_2019.pdf).

The 203,830 CIFs you provided are already local. The current ICSD site shows the database still
growing, and bulk/API use requires separate authorization, so nothing is scraped automatically. To
update to the current version you must supply institutional access with bulk/API rights and confirm
that the licence permits a local offline copy.

### NIMS AtomWork-Adv

Entry points: [service and
licence](https://atomwork-adv.nims.go.jp/en/service.html), [purchase /
application](https://purchase-atomwork.nims.go.jp/index).

The site currently lists about 409,723 structures and 568,195 properties. The 72-hour trial allows
search/browse only, not download; a paid licence typically caps downloads at 5,000 records per year,
and the full database must be negotiated separately with NIMS. You need to complete DICE account
setup, the trial application and licence purchase, or ask AtomWork-Adv directly about full-database
authorization.

### SpringerMaterials, Pearson's Crystal Data, ICDD PDF-4+

- [SpringerMaterials](https://materials.springer.com/): needs a personal or institutional
  subscription; bulk/API rights depend on the contract.
- [Pearson's Crystal Data](https://www.crystalimpact.com/pcd/): a commercial database requiring a
  Crystal Impact licence.
- [ICDD PDF-4+](https://www.icdd.com/pdf-4/): a commercial powder diffraction database requiring an
  ICDD licence; scraping is not a substitute for an authorized export.

If the university already holds an institutional licence, first confirm whether it permits bulk
export, offline storage and internal search; ingest only after explicit permission.

### Actions required for third-round sources

- [NIMS AtomWork open](https://crystdb.nims.go.jp/en/): register a DICE account, complete email
  domain registration and submit the MatNavi usage application. After approval, use the TSV/structure
  export the page provides; the site explicitly prohibits web scraping.
- [Matterverse](https://optimade.matterverse.ai/): contact the provider for a bulk snapshot of the
  31,791,192 structures. Public OPTIMADE caps pages at 500 records, so a direct full mirror would
  need about 63,583 requests, which must not substitute for a proper bulk transfer.
- [MOF DB](https://mofdb.org/): log in to the linked Hugging Face account, accept the H2MOF-ML/hMOF-ML
  repository conditions, then set the token only in a local environment variable; never write the
  token into Git or chat.
- [ADAQ](https://defects.anyterial.se/): explain to the site maintainers that you intend to build a
  local research mirror and request substantial replication permission; the current licence page only
  clearly permits non-substantial extracts.
- [MatGen](https://matgen.nscc-gz.cn/index_ch.html): register an account or email
  `matgen@nscc-gz.cn` to request bulk/API access for the inorganic, hypothetical, 2D, superconductor
  and solid-electrolyte libraries; the molten-salt MD library is out of scope.
- [Atomly](https://atomly.net/): email `atomly@iphy.ac.cn` for collaborator API access. The official
  frontend states the API is currently for internal testing and collaborators only.
- [MatCloud+](https://www.matcloud.com.cn/newDataBase/structure): after registering, request an
  account-level bulk export and confirm whether each library permits offline storage and
  redistribution.
- [MatCraft](https://matcraft.ai/docs/materials-api/authentication): if their aggregated
  MP/AFLOW/JARVIS records are still wanted, log in to generate an API token, then request bulk export
  authorization beyond the normal rate limit; the terms prohibit over-limit scraping.
- [2D hybrid perovskites](https://arxiv.org/abs/2006.14302), [OpenMX
  AB₂](https://www.openmx-square.org/2d-ab2/) and [NLR MatDB](https://materials.nlr.gov/): all are
  interactively accessible today, but no secure, clearly licensed full-database package was found.
  Contact the authors/maintainers for bulk files rather than scraping page by page.
- [HPCSD](https://www.calypso.cn/): register a CALYPSO/HPCSD account and ask the paper authors or
  site maintainers for a bulk snapshot of the 77,346 first-release structures; ingest only final
  static structures and properties, never search populations or evolutionary trajectories.
- [PowBase](https://www.cristal.org/powbase/index.html): the site requires mirrors to contact the
  maintainer first. Obtain permission for a local research mirror of the 169 static
  structure/powder-pattern packages, then tell me to continue.
- [MinCryst](https://database.iem.ac.ru/mincryst/) and [Webmineral](https://webmineral.com/): the
  former's host is currently unreachable and the latter has no clear bulk atomic-coordinate export;
  request the current static structure snapshot and usage terms from the maintainers.
- [NIST Crystal Data](https://www.nist.gov/publications/nist-3-nist-crystal-data) and [NIST Surface
  Structure Database](https://www.nist.gov/publications/nist-42-nist-surface-structure-database-version-30):
  confirm whether the university holds a NIST SRD licence; without one, purchase or request the
  current release package from NIST rather than scraping.
- [NIMS PhononDB](https://mdr.nims.go.jp/collections/8g84ms862?locale=en): contact NIMS MDR or the
  data authors for a collection-level bulk snapshot of the 10,034 records; downloading per record
  would need about 10,000 page and file requests, which must not replace a proper package. Once
  obtained, ingest only the static unit cell and phonon properties per MP ID, treating displacement
  supercells as non-unique structures.

### OMDB, MPOD and the topological materials database

- The official bulk button on [OMDB](https://omdb.mathub.io/dataset/) currently redirects to login;
  this round obtained the same 12.5k-scale open data from the NIST JARVIS/Figshare mirror. The
  official latest version requires registering an OMDB account and downloading manually.
- The new [AMCSD / RRUFF](https://www.rruff.net/about/download-data/) download page now publishes
  CIF, AMC, DIF and assorted property ZIPs, so this round added resumable full-database downloads and
  no longer needs page-by-page scraping.
- [MPOD](https://mpod.cimav.edu.mx/) offers per-record `.mpod` tensor property files, but the site is
  slow and no official bulk index was found; recorded as a later low-frequency/API ingestion item.
- The [Topological Materials Database](https://topologicalquantumchemistry.org/) currently shows about
  38,184 materials, but its structures and classifications derive from ICSD and other licensed data,
  and no redistributable full-database download was found. With the corresponding ICSD rights it can
  be joined to the local ICSD by ID rather than scraped.

## 6. Integrity checks

After static files complete:

```bash
find -L data/raw/acquired -type f -name '*.receipt.json' -print
find -L data/raw/acquired -type f -name '*.part' -print
df -h /home/zhilong/SSD
```

API tasks count as complete when `manifest.json` holds `complete: true` and
`downloaded_documents == total_documents`. Archives are then fully verified with `gzip -t`,
`bzip2 -t`, `unzip -t` or `tar -tzf`; database contents are converted through each source's adapter
and then checked for structure parsing, element/formula consistency, units and duplicate structures.

## 7. Deduplication and source priority

The same structure may appear simultaneously in ICSD, COD, MPDS, MP, OQMD, AFLOW, Alexandria, GNoME
and training-set snapshots. Ingestion never overwrites by material name; it uses the following keys
and rules:

1. Retain `source`, `source_version`, `source_id`, `license`, `retrieved_at`.
2. Compute a structural fingerprint over normalised occupancies, lattice and fractional coordinates;
   hash exactly first, then run tolerance-based structure matching.
3. Label experimental structures and computational initial/final relaxed structures separately; a
   computational candidate must never be written up as experimentally synthesised, and intermediate
   trajectory configurations are not collected.
4. Duplicate structures merge only the retrieval entity and never discard source-specific properties;
   properties keep their calculation method, functional, temperature/pressure conditions and units.
5. More strictly licensed data must never be redistributed "contagiously" through a more permissive
   dataset; the frontend exposes only the fields and download actions the current authorization
   permits.
