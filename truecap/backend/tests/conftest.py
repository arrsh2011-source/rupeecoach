import pytest

from truecap.domain import FactSet, Ledger, SourceType
from truecap.sample_data import FETCHED, sample_ctx


class Builder:
    """Small helper to build a FactSet with one evidence entry per source type."""

    def __init__(self) -> None:
        self.ledger = Ledger()
        self.facts = FactSet(self.ledger)
        self._sources: dict[SourceType, str] = {}

    def src(self, source_type: SourceType = SourceType.MCA, url: str | None = None) -> str:
        if url is None and source_type in self._sources:
            return self._sources[source_type]
        e = self.ledger.add(f"{source_type.value} source", source_type,
                            url=url or f"https://{source_type.value}.example/doc", fetched_at=FETCHED)
        self._sources.setdefault(source_type, e.id)
        return e.id

    def put(self, key: str, value, source_type: SourceType = SourceType.MCA) -> "Builder":
        self.facts.put(key, value, self.src(source_type))
        return self


@pytest.fixture
def b() -> Builder:
    return Builder()


@pytest.fixture
def ctx():
    return sample_ctx()
