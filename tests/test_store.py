import threading

from lookbrief.store import Store


def test_concurrent_reads_never_return_wrong_rows(tmp_path):
    """One SQLite connection is shared by request threads; rows must be fetched under the lock
    (parallel brief image requests once got None back and answered 500)."""
    st = Store(tmp_path / "db.sqlite")
    sid, _ = st.create_session("replay", "s", "1.1.1.1", consent=False)
    briefs = [st.create_brief(sid, {"images": {"a": "a.jpg"}, "review_zones": []})["id"] for _ in range(20)]
    errors = []

    def worker() -> None:
        for _ in range(200):
            for bid in briefs:
                b = st.brief(bid)
                if b is None or b["id"] != bid:
                    errors.append(bid)

    threads = [threading.Thread(target=worker) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert not errors, f"{len(errors)} wrong reads"


def test_review_change_withdraws_and_hash_tracks_answers(tmp_path):
    st = Store(tmp_path / "db.sqlite")
    sid, _ = st.create_session("replay", "s", "1.1.1.1", consent=False)
    bid = st.create_brief(sid, {"review_zones": ["eyes"]})["id"]
    assert st.set_review(bid, 1, "eyes", "do", "") is True
    h1 = st.reviews_sha(bid, 1)
    st.agree(bid, 1, "artist")
    assert st.set_review(bid, 1, "eyes", "do", "") is False, "identical answer is not a change"
    assert st.agreements(bid, 1) == {"artist": st.agreements(bid, 1)["artist"]}
    assert st.set_review(bid, 1, "eyes", "swap", "cooler") is True
    assert st.agreements(bid, 1) == {} and st.reviews_sha(bid, 1) != h1
