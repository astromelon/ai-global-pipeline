"""Node 4 게이트 차단 내역 리포트 — Claude·agy·Codex 게이트 로그를 합쳐 최근 순으로 보여준다.

읽는 로그(회전된 .1 포함):
  Claude: ~/.claude/hooks/node4-approval-gate.log            (decision=ask  → 확인창)
  agy   : ~/.gemini/config/hooks/node4-approval-gate-agy.log   (decision=deny → 차단)
  Codex : ~/.codex/hooks/node4-approval-gate-codex.log        (decision=log  → 기록만, 판정은 execpolicy)

사용 예:
  python gate_report.py                 # 최근 20건
  python gate_report.py -n 50 --since 7d
  python gate_report.py --tool agy --since 2026-11-01
  python gate_report.py --json          # 합친 레코드를 JSON 배열로 출력
"""
import argparse
import datetime
import json
import os
import re
import sys

HOME = os.path.expanduser("~")
SOURCES = {
    "claude": os.path.join(HOME, ".claude", "hooks", "node4-approval-gate.log"),
    "agy": os.path.join(HOME, ".gemini", "config", "hooks", "node4-approval-gate-agy.log"),
    "codex": os.path.join(HOME, ".codex", "hooks", "node4-approval-gate-codex.log"),
}


def short_decision(decision: str) -> str:
    """표 출력용 판정 이름. Codex 기록 훅의 'logged-only (...)'는 'log'로 줄인다."""
    return "log" if decision.startswith("logged-only") else decision


def read_records(tool: str, path: str) -> list:
    """한 도구의 로그(.1 → 현재 순)를 읽어 공통 형식으로 바꾼다. 깨진 줄은 건너뛴다."""
    records = []
    for candidate in (path + ".1", path):
        if not os.path.exists(candidate):
            continue
        with open(candidate, encoding="utf-8") as log:
            for line_no, line in enumerate(log, 1):
                try:
                    raw = json.loads(line)
                    ts = datetime.datetime.fromisoformat(raw["ts"])
                except (ValueError, KeyError, TypeError):
                    print(f"[경고] {os.path.basename(candidate)}:{line_no} 읽기 실패, 건너뜀", file=sys.stderr)
                    continue
                workspace = raw.get("workspace")
                records.append({
                    "ts": ts,
                    "tool": tool,
                    "decision": short_decision(raw.get("decision", "?")),
                    "hits": raw.get("hits") or [],
                    "command": raw.get("command", ""),
                    "session": raw.get("session_id") or raw.get("conversation_id") or "",
                    "cwd": raw.get("cwd") or (workspace[0] if isinstance(workspace, list) and workspace else ""),
                    "permission_mode": raw.get("permission_mode") or "",
                })
    return records


def parse_since(value: str) -> datetime.datetime:
    """'24h' / '7d' / '2026-11-01' 형식을 시각으로 바꾼다."""
    now = datetime.datetime.now().astimezone()
    match = re.fullmatch(r"(\d+)([hd])", value)
    if match:
        amount, unit = int(match.group(1)), match.group(2)
        return now - datetime.timedelta(hours=amount if unit == "h" else amount * 24)
    since = datetime.datetime.fromisoformat(value)
    return since if since.tzinfo else since.astimezone()


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description="Node 4 게이트 차단 내역 (Claude + agy + Codex)")
    parser.add_argument("-n", "--limit", type=int, default=20, help="표시할 최대 건수 (기본 20)")
    parser.add_argument("--since", help="이 시점 이후만: 24h, 7d, 2026-11-01")
    parser.add_argument("--tool", choices=sorted(SOURCES), help="한 도구만 보기")
    parser.add_argument("--json", action="store_true", help="JSON 배열로 출력")
    args = parser.parse_args()

    records = []
    for tool, path in SOURCES.items():
        if args.tool in (None, tool):
            records.extend(read_records(tool, path))
    if args.since:
        since = parse_since(args.since)
        records = [r for r in records if r["ts"] >= since]
    total = len(records)
    records.sort(key=lambda r: r["ts"], reverse=True)
    shown = records[: max(args.limit, 0)]

    if args.json:
        print(json.dumps([{**r, "ts": r["ts"].isoformat()} for r in shown], ensure_ascii=False, indent=2))
        return 0

    by_tool = {}
    for r in records:
        by_tool[r["tool"]] = by_tool.get(r["tool"], 0) + 1
    summary = ", ".join(f"{tool} {count}" for tool, count in sorted(by_tool.items())) or "없음"
    print(f"Node 4 게이트 기록 {total}건 ({summary}) — 최근 {len(shown)}건 표시")
    if not shown:
        return 0
    print(f"{'시각':<19}  {'도구':<6} {'판정':<4}  {'걸린 항목':<16} 명령")
    print("-" * 100)
    for r in shown:
        hits = ",".join(r["hits"])
        command = r["command"] if len(r["command"]) <= 60 else r["command"][:59] + "…"
        print(f"{r['ts'].strftime('%Y-%m-%d %H:%M:%S'):<19}  {r['tool']:<6} {r['decision']:<4}  {hits:<16} {command}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
