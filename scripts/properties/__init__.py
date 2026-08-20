"""Cross-database property matching and ingestion for MateriaViva.

The pipeline turns raw acquired sources (data/raw/acquired/<source>) into:

1. property rows attached to existing pool materials, every row tagged with its
   source database and native record id;
2. new structure master records for crystals the pool does not contain yet,
   deduplicated with the same primitive-reduced BAWL fingerprint as the
   original merge.

Stages are resumable and auditable; all intermediates live under
``data/props_work/<source>/``.
"""
