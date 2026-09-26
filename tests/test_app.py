"""画面（trip_app.py）の動作テスト。Streamlit の AppTest で実際にスクリプトを動かす。"""

from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

APP = str(Path(__file__).resolve().parent.parent / "trip_app.py")


def button(at: AppTest, label: str):
    return next(b for b in at.button if b.label == label)


@pytest.fixture
def at() -> AppTest:
    app = AppTest.from_file(APP, default_timeout=60)
    app.run()
    assert not app.exception
    return app


def generate(at: AppTest) -> None:
    next(n for n in at.number_input if n.label.startswith("金額")).set_value(200000).run()
    button(at, "🎲 旅をつくる").click().run()
    assert not at.exception
    assert at.session_state.plan is not None


def test_generate_and_reroll_other_destination(at):
    generate(at)
    first = at.session_state.plan.dest["id"]
    button(at, "🎲 別の行き先で引き直す").click().run()
    assert not at.exception
    assert at.session_state.plan.dest["id"] != first
    # 引き直した旅は行き先指定の旅コードになり、同じ行き先を再現できる
    assert at.session_state.plan.trip_code.endswith(at.session_state.plan.dest["id"])


def test_reroll_does_not_bounce_back_to_seen_destinations(at):
    generate(at)
    seen = [at.session_state.plan.dest["id"]]
    for _ in range(4):
        button(at, "🎲 別の行き先で引き直す").click().run()
        seen.append(at.session_state.plan.dest["id"])
    assert len(set(seen)) == len(seen)


def test_replay_trip_code_reproduces_plan(at):
    generate(at)
    plan = at.session_state.plan
    at.text_input[0].input(plan.trip_code).run()
    button(at, "🎲 旅をつくる").click().run()          # 旅コードが入っていても、メインボタンはランダムのまま
    button(at, "このコードで再現する").click().run()
    assert not at.exception
    assert at.session_state.plan.title == plan.title
    assert at.session_state.plan.total == plan.total


def test_invalid_code_shows_error_once(at):
    at.text_input[0].input("12345").run()
    button(at, "このコードで再現する").click().run()
    assert any("旅コード" in e.value for e in at.error)
    at.run()
    assert not at.error


def test_party_size_survives_solo_toggle(at):
    at.number_input(key="adults").set_value(3).run()
    relation = next(r for r in at.radio if r.label == "関係性")
    relation.set_value("solo").run()
    relation = next(r for r in at.radio if r.label == "関係性")
    relation.set_value("friends").run()
    assert at.number_input(key="adults").value == 3


def test_detail_level_changes_view_not_trip(at):
    generate(at)
    title = at.session_state.plan.title
    slider = next(s for s in at.select_slider if s.label == "決め込み度")
    for level in (1, 5):
        slider.set_value(level).run()
        assert not at.exception
        assert at.session_state.plan.title == title
