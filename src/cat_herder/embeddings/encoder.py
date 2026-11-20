import logging
import platform
from collections.abc import Sequence
from pathlib import Path
from typing import Protocol

import numpy
import tokenizers

type Vectors = numpy.ndarray[tuple[int, int], numpy.dtype[numpy.float32]]

# all-MiniLM-L6-v2, pinned, in the int8 build for the machine's processor family
_REPOSITORY = 'sentence-transformers/all-MiniLM-L6-v2'
_REVISION = '1110a243fdf4706b3f48f1d95db1a4f5529b4d41'
_ARM_GRAPH = 'onnx/model_qint8_arm64.onnx'
_X86_GRAPH = 'onnx/model_quint8_avx2.onnx'
_TOKENIZER = 'tokenizer.json'
# where models are downloaded to, under the data directory
_MODELS_DIRECTORY = 'models'
_MAX_TOKENS = 256
# all-MiniLM-L6-v2's usual cut-off: texts on unrelated topics score below it, a query and a passage on its topic above
_MIN_SIMILARITY = 0.3
_BATCH_SIZE = 32


class Encoder(Protocol):
    """Turns texts into embeddings: unit vectors whose dot product is higher the closer the texts' meanings are."""

    @property
    def model(self) -> str:
        """The model and its exact build. Embeddings from different ones can't be compared."""
        ...

    @property
    def max_tokens(self) -> int:
        """How many tokens of a text it reads, its own markers included. It ignores the rest."""
        ...

    @property
    def min_similarity(self) -> float:
        """The dot product two texts' embeddings must exceed for their meanings to count as related."""
        ...

    def token_spans(self, text: str) -> list[tuple[int, int]]:
        """Where each of the text's tokens starts and ends, as character offsets, without its own markers."""
        ...

    def encode(self, texts: Sequence[str]) -> Vectors:
        """One embedding per text, in order."""
        ...


class EncoderUnavailable(Exception):
    """The model can't be downloaded or loaded. The message says why."""


def load_encoder(data_dir: Path) -> Encoder:
    """from the data directory, downloading it there first if it's missing.

    Raises:
        EncoderUnavailable: if it can't be downloaded or loaded.
    """
    graph = _ARM_GRAPH if platform.machine().lower() in ('arm64', 'aarch64') else _X86_GRAPH
    directory = data_dir / _MODELS_DIRECTORY / _REPOSITORY.replace('/', '__') / _REVISION
    graph_path = _downloaded(directory, graph)
    tokenizer_path = _downloaded(directory, _TOKENIZER)
    return _OnnxEncoder(f'{_REPOSITORY}@{_REVISION}/{graph}', graph_path, tokenizer_path)


class _OnnxEncoder:
    def __init__(self, model: str, graph_path: Path, tokenizer_path: Path) -> None:
        import onnxruntime  # pyright: ignore[reportMissingTypeStubs]

        self._model = model
        try:
            self._session = onnxruntime.InferenceSession(str(graph_path), providers=['CPUExecutionProvider'])
        except Exception as error:  # onnxruntime's errors have no common base but Exception
            raise EncoderUnavailable(
                f'{graph_path} could not be loaded, delete it to download it again: {error}'
            ) from error
        # the published tokenizer pads and truncates to 128 tokens, which suits neither use
        self._reader = tokenizers.Tokenizer.from_file(str(tokenizer_path))
        self._reader.enable_truncation(max_length=_MAX_TOKENS)  # pyright: ignore[reportUnknownMemberType]
        self._reader.enable_padding()  # pyright: ignore[reportUnknownMemberType]
        self._counter = tokenizers.Tokenizer.from_file(str(tokenizer_path))
        self._counter.no_truncation()
        self._counter.no_padding()

    @property
    def model(self) -> str:
        return self._model

    @property
    def max_tokens(self) -> int:
        return _MAX_TOKENS

    @property
    def min_similarity(self) -> float:
        return _MIN_SIMILARITY

    def token_spans(self, text: str) -> list[tuple[int, int]]:
        return list(self._counter.encode(text, add_special_tokens=False).offsets)

    def encode(self, texts: Sequence[str]) -> Vectors:
        vectors = numpy.zeros((len(texts), 0), dtype=numpy.float32)
        order = sorted(range(len(texts)), key=lambda index: len(texts[index]))
        for start in range(0, len(texts), _BATCH_SIZE):
            batch = order[start:start + _BATCH_SIZE]
            encoded = self._encode_batch([texts[index] for index in batch])
            if not vectors.shape[1]:
                vectors = numpy.zeros((len(texts), encoded.shape[1]), dtype=numpy.float32)
            vectors[batch] = encoded
        return vectors

    def _encode_batch(self, texts: list[str]) -> Vectors:
        encodings = self._reader.encode_batch(texts)
        ids = numpy.array([encoding.ids for encoding in encodings], dtype=numpy.int64)
        mask = numpy.array([encoding.attention_mask for encoding in encodings], dtype=numpy.int64)
        feed = {'input_ids': ids, 'attention_mask': mask, 'token_type_ids': numpy.zeros_like(ids)}
        outputs = self._session.run(None, feed)  # pyright: ignore[reportUnknownMemberType, reportUnknownVariableType]
        tokens = numpy.asarray(outputs[0], dtype=numpy.float32)  # pyright: ignore[reportUnknownArgumentType]
        pooled = (tokens * mask[..., None]).sum(axis=1) / mask.sum(axis=1, keepdims=True)
        return (pooled / numpy.linalg.norm(pooled, axis=1, keepdims=True)).astype(numpy.float32)


def _downloaded(directory: Path, filename: str) -> Path:
    path = directory / filename
    if path.exists():
        return path
    from huggingface_hub import hf_hub_download  # pyright: ignore[reportUnknownVariableType]

    logging.getLogger('huggingface_hub').setLevel(logging.ERROR)
    try:
        return Path(hf_hub_download(_REPOSITORY, filename, revision=_REVISION, local_dir=directory))
    except OSError as error:
        raise EncoderUnavailable(f'{_REPOSITORY} could not be downloaded: {error}') from error
