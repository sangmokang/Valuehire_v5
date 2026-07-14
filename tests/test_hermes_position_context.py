from tools.multi_position_sourcing.hermes_position_context import PositionContextStore


def test_context_isolated_by_user_and_channel_and_expires(tmp_path):
    clock = [1000.0]
    store = PositionContextStore(tmp_path / "context.sqlite3", now=lambda: clock[0])
    store.put("u1", "c1", "https://app.clickup.com/t/one", ("saramin",))
    assert store.get("u1", "c1").position_url.endswith("/one")
    assert store.get("u2", "c1") is None
    assert store.get("u1", "c2") is None
    clock[0] += 1801
    assert store.get("u1", "c1") is None
