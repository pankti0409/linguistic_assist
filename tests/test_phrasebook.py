import pytest

from app.core.consent import ConsentRegistry
from app.core.errors import ConsentRequiredError
from app.core.phrasebook import InvalidProfileError, Phrasebook, ProfileTerms


def _pb(tmp_path, granted=True):
    c = ConsentRegistry()
    if granted:
        c.grant("personalization")
    return Phrasebook(tmp_path / "pb.json", c), c


def test_retrieval_by_token_overlap(tmp_path):
    pb, _ = _pb(tmp_path)
    pb.add("I would like cold water, please.", edited=False)
    pb.add("Please call my daughter.", edited=False)
    pb.add("I am tired.", edited=False)
    hits = pb.search(["water", "cold"], k=5)
    assert hits[0].text.startswith("I would like cold water")
    assert all("tired" not in h.text for h in hits)  # zero overlap is never returned
    assert len(pb.search(["water"], k=1)) == 1


def test_edited_counts_double_and_persists(tmp_path):
    pb, c = _pb(tmp_path)
    pb.add("I want tea", edited=True)
    pb.add("i want tea", edited=False)
    assert pb.entries()[0].uses == 3
    again = Phrasebook(tmp_path / "pb.json", c)
    assert again.entries()[0].uses == 3


def test_ties_prefer_more_uses(tmp_path):
    pb, _ = _pb(tmp_path)
    pb.add("water now", edited=False)
    pb.add("water later", edited=True)
    assert pb.search(["water"], k=2)[0].text == "water later"


def test_refuses_without_personalization_consent(tmp_path):
    pb, c = _pb(tmp_path, granted=False)
    assert pb.add("I want tea", edited=False) is None
    assert pb.search(["tea"], 5) == []
    with pytest.raises(ConsentRequiredError):
        pb.entries()
    assert not (tmp_path / "pb.json").exists()


def test_wipe_is_always_allowed(tmp_path):
    pb, c = _pb(tmp_path)
    pb.add("I want tea", edited=False)
    c.revoke("personalization")
    assert pb.wipe() == 1
    assert not (tmp_path / "pb.json").exists()


def test_profile_terms(tmp_path):
    c = ConsentRegistry()
    terms = ProfileTerms(tmp_path / "t.json", c)
    with pytest.raises(ConsentRequiredError):
        terms.put(["Meera"])
    assert terms.for_packet() == []
    c.grant("personalization")
    assert terms.put([" Meera ", "Meera", "Apollo  Hospital", ""]) == ["Meera", "Apollo Hospital"]
    assert ProfileTerms(tmp_path / "t.json", c).get() == ["Meera", "Apollo Hospital"]
    with pytest.raises(InvalidProfileError):
        terms.put(["x" * 61])


def test_phrasebook_and_profile_api(client):
    assert client.get("/phrasebook").status_code == 403
    assert client.put("/profile/terms", json=["Meera"]).status_code == 403
    client.post("/consent", json={"purpose": "personalization"})
    assert client.put("/profile/terms", json=["Meera"]).json() == ["Meera"]
    assert client.get("/profile/terms").json() == ["Meera"]
    client.app.state.phrasebook.add("I want tea", edited=False)
    assert [e["text"] for e in client.get("/phrasebook").json()] == ["I want tea"]
    assert client.delete("/phrasebook").json() == {"deleted": 1}
    assert client.get("/phrasebook").json() == []
