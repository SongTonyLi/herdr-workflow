import json
import multiprocessing as mp

from hw.state import Store, new_state


def _bump(root, n):
    st = Store(root)
    for _ in range(n):
        with st.mutate() as s:
            s["seq"]["task"] += 1
        st.event("bump")


def test_concurrent_mutations_are_serialized(tmp_path):
    st = Store(tmp_path)
    st.create(new_state("r", "g", "main", {"models": {}, "kind_tier": {}}))
    procs = [mp.Process(target=_bump, args=(tmp_path, 25)) for _ in range(6)]
    for p in procs:
        p.start()
    for p in procs:
        p.join()
    assert st.read()["seq"]["task"] == 150
    assert len(st.events()) == 150
    assert (tmp_path / ".hw" / "TODO.md").exists()
    # no temp files left behind by atomic writes
    assert not list((tmp_path / ".hw").glob(".state.*.tmp"))
    json.loads((tmp_path / ".hw" / "state.json").read_text())
