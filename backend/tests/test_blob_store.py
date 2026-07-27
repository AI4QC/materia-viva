from materials_api.blob_store import BlobReader, BlobWriter


def test_blob_store_round_trips_multiple_cifs_by_offset(tmp_path):
    path = tmp_path / "structures.blob"
    first = "data_LiFePO4\n_cell_length_a 10.1\n"
    second = "data_Si\n_cell_length_a 5.43\n" * 20

    with BlobWriter(path) as writer:
        first_ref = writer.append(first)
        second_ref = writer.append(second)

    with BlobReader(path) as reader:
        assert reader.read(first_ref.offset, first_ref.length) == first
        assert reader.read(second_ref.offset, second_ref.length) == second

    assert first_ref.offset == 0
    assert second_ref.offset == first_ref.length


def test_blob_store_detects_corrupt_payload(tmp_path):
    path = tmp_path / "structures.blob"
    path.write_bytes(b"not-zlib")

    with BlobReader(path) as reader:
        try:
            reader.read(0, len(b"not-zlib"))
        except ValueError as exc:
            assert "corrupt" in str(exc).lower()
        else:
            raise AssertionError("corrupt payload should fail")
