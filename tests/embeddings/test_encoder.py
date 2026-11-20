from pathlib import Path

import huggingface_hub
import numpy
import pytest

from cat_herder.embeddings.encoder import Encoder, EncoderUnavailable, load_encoder


@pytest.fixture(scope='module')
def encoder(tmp_path_factory: pytest.TempPathFactory) -> Encoder:
    # Downloaded once for every test of the real model.
    return load_encoder(tmp_path_factory.mktemp('data'))


def test_load_encoder_reports_a_model_it_cannot_download(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    # GIVEN
    def unreachable(*_: object, **__: object) -> str:
        raise OSError('no network')

    monkeypatch.setattr(huggingface_hub, 'hf_hub_download', unreachable)

    # WHEN
    with pytest.raises(EncoderUnavailable) as raised:
        load_encoder(tmp_path)

    # THEN
    assert str(raised.value) == 'sentence-transformers/all-MiniLM-L6-v2 could not be downloaded: no network'


def test_load_encoder_reports_a_model_it_cannot_load(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    # GIVEN a download that writes something other than a model
    def download(_: str, filename: str, *, local_dir: Path, **__: object) -> str:
        path = local_dir / filename
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text('not a model')
        return str(path)

    monkeypatch.setattr(huggingface_hub, 'hf_hub_download', download)

    # WHEN
    with pytest.raises(EncoderUnavailable) as raised:
        load_encoder(tmp_path)

    # THEN
    assert 'could not be loaded, delete it to download it again' in str(raised.value)


@pytest.mark.embedding_model
def test_the_model_embeds_texts_closer_the_closer_their_meanings(encoder: Encoder):
    # WHEN a text longer than the model reads, as well
    vectors = encoder.encode(['The disk is full', 'Storage is running out', 'A concert recording', 'word ' * 400])

    # THEN unit vectors, and storage closer to a full disk than a concert is
    assert vectors.shape == (4, 384)
    assert numpy.allclose(numpy.linalg.norm(vectors, axis=1), 1, atol=1e-5)
    assert vectors[0] @ vectors[1] > vectors[0] @ vectors[2] + 0.2


@pytest.mark.embedding_model
def test_the_model_finds_tokens_where_the_text_has_them(encoder: Encoder):
    # WHEN
    spans = encoder.token_spans('Disk full')

    # THEN
    assert spans == [(0, 4), (5, 9)]
