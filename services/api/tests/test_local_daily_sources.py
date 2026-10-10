from pathlib import Path
import subprocess

import pytest

from scripts import run_scheduled_daily as scheduled


@pytest.fixture
def daily(monkeypatch):
    monkeypatch.delenv("LOCAL_MARKET_ARCHIVE",raising=False)
    monkeypatch.delenv("LOCAL_MARKET_ARCHIVE_BACKUP",raising=False)
    monkeypatch.setenv("SEC_USER_AGENT","archive-tests test@example.test")
    monkeypatch.setattr(scheduled,"get_supabase",lambda:object())
    monkeypatch.setattr(scheduled,"refresh_plan",lambda *args:{"run_market":True,"run_sources":True})


@pytest.mark.parametrize("failure",[("refresh_research_sources.py",("--sec-only","--max-age-hours","24")),
                                    ("refresh_analyst_consensus.py",("--max-age-hours","24")),
                                    ("refresh_enrichment.py",())])
def test_optional_failure_preserves_publication_and_remaining_collection(daily,monkeypatch,capsys,failure):
    calls=[]
    def run(command,**kwargs):
        step=(Path(command[1]).name,tuple(command[2:]))
        calls.append(step)
        if step==failure:
            raise subprocess.CalledProcessError(1,command)
    monkeypatch.setattr(scheduled.subprocess,"run",run)
    scheduled.main()
    assert ("run_weekly_cycle.py",()) in calls
    assert calls[-1]==("refresh_enrichment.py",())
    output=capsys.readouterr()
    assert "Optional coverage incomplete" in output.err
    assert failure[0] in output.err
    assert "Daily market and earnings refresh completed" in output.out


@pytest.mark.parametrize("failure",["run_daily_cycle.py","validate_daily_cycle.py","run_weekly_cycle.py"])
def test_required_failure_stops_before_optional_enrichment(daily,monkeypatch,capsys,failure):
    calls=[]
    def run(command,**kwargs):
        name=Path(command[1]).name
        calls.append(name)
        if name==failure:
            raise subprocess.CalledProcessError(1,command)
    monkeypatch.setattr(scheduled.subprocess,"run",run)
    with pytest.raises(subprocess.CalledProcessError):
        scheduled.main()
    assert calls[-1]==failure
    assert "refresh_enrichment.py" not in calls
    assert "refresh completed" not in capsys.readouterr().out


def test_archive_failure_prevents_any_market_or_publication_work(daily,monkeypatch):
    monkeypatch.setenv("LOCAL_MARKET_ARCHIVE","primary.sqlite3")
    monkeypatch.setenv("LOCAL_MARKET_ARCHIVE_BACKUP","backup.sqlite3")
    calls=[]
    def run(command,**kwargs):
        calls.append(Path(command[1]).name)
        raise subprocess.CalledProcessError(1,command)
    monkeypatch.setattr(scheduled.subprocess,"run",run)
    with pytest.raises(subprocess.CalledProcessError):
        scheduled.main()
    assert calls==["archive_market_history.py"]


def test_missing_sec_contact_remains_visible(daily,monkeypatch,capsys):
    monkeypatch.delenv("SEC_USER_AGENT")
    calls=[]
    monkeypatch.setattr(scheduled.subprocess,"run",lambda command,**kwargs:calls.append(command))
    scheduled.main()
    assert not any("--sec-only" in c for c in calls)
    assert "SEC_USER_AGENT missing" in capsys.readouterr().err


def test_earnings_failure_collects_other_sources_but_blocks_publication(daily,monkeypatch,capsys):
    calls=[]
    def run(command,**kwargs):
        step=(Path(command[1]).name,tuple(command[2:]))
        calls.append(step)
        if "--earnings-only" in command:
            raise subprocess.CalledProcessError(1,command)
    monkeypatch.setattr(scheduled.subprocess,"run",run)
    with pytest.raises(RuntimeError,match="Required earnings refresh failed"):
        scheduled.main()
    assert any("--sec-only" in args for _,args in calls)
    assert ("refresh_enrichment.py",()) in calls
    assert ("run_weekly_cycle.py",()) not in calls
    assert "Daily market and earnings refresh completed" not in capsys.readouterr().out


def test_completed_market_still_recovers_sources(daily,monkeypatch):
    monkeypatch.setattr(scheduled,"refresh_plan",lambda *args:{"run_market":False,"run_sources":True})
    calls=[]
    monkeypatch.setattr(scheduled.subprocess,"run",lambda command,**kwargs:calls.append(command))
    scheduled.main()
    assert not any(Path(c[1]).name=="run_daily_cycle.py" for c in calls)
    assert any("--earnings-only" in c for c in calls)
    assert any("--sec-only" in c for c in calls)
    assert any(Path(c[1]).name=="run_weekly_cycle.py" for c in calls)


def test_active_market_does_not_start_sources_or_publication(daily,monkeypatch):
    monkeypatch.setattr(scheduled,"refresh_plan",lambda *args:{"run_market":False,"run_sources":False})
    calls=[]
    monkeypatch.setattr(scheduled.subprocess,"run",lambda command,**kwargs:calls.append(command))
    scheduled.main()
    assert calls==[]
