"""게이트 훅 동기화 테스트 자동 실행 — Claude·Codex·Gemini·agy 공용 사후 훅.

사용: python sync_test_hook.py [--format claude|codex|gemini|agy]  (기본 claude)
  claude : PostToolUse   → decision=block + reason + additionalContext
  codex  : PostToolUse   → claude 와 같은 형식
  gemini : AfterTool     → additionalContext(도구 결과 뒤에 덧붙임) + systemMessage. decision 은 쓰지 않는다
                            (Gemini 에서 decision=block 은 도구 결과 자체를 가린다)
  agy    : PostInvocation → injectSteps 의 ephemeralMessage (agy PostToolUse 는 응답 수단이 없다)
감시 파일의 수정 시각을 도구 호출마다 확인하고, 바뀐 경우에만 (마스터 규칙 사본 갱신 →)
test_gate_hooks_in_sync.py 를 실행한다. Edit/Write 뿐 아니라 셸 스크립트로 고친 경우도 수정 시각으로 잡는다.

감지·갱신·테스트는 전체에서 한 번만 한다(잠금 파일로 동시 실행 방지). 그 결과는 '이벤트'로 남기고,
알림은 **세션마다 한 번씩** 전달한다. 세션 키 = 형식 + 훅 입력의 세션 id
(Claude·Codex·Gemini: session_id, agy: conversationId). 세션은 마지막으로 받은 이벤트 번호를 기억한다.
- 이미 알던 세션: 그 뒤 이벤트를 받는다. 마지막 이벤트가 실패면 실패 알림, 아니면 그사이 자동 갱신 알림.
  (실패 뒤 통과로 이미 해소된 실패는 알리지 않는다.)
- 처음 보는 세션: 지난 이벤트는 건너뛴다(시작할 때 이미 최신 규칙을 읽었다). 단 지금 실패 상태면 알리고,
  이번 호출이 직접 만든 이벤트는 받는다.
- 세션 id 가 없는 입력: 이번 호출이 직접 만든 이벤트만 받는다(예전 동작).

출력 형식
- 통과 + 자동 갱신: 막지 않는 알림(additionalContext + systemMessage, agy 는 ephemeralMessage).
- 실패: claude/codex 는 decision=block, gemini 는 additionalContext, agy 는 ephemeralMessage.
- 첫 실행(상태 파일 없음): 현재 수정 시각만 기록하고 넘어간다.
- 이 훅 자체의 오류는 삼켜서 일반 작업을 막지 않는다.
검증용 덮어쓰기: NODE4_SYNC_STATE_DIR(상태·이벤트·세션·잠금·로그 파일 위치, 기본은 이 폴더).
"""
import json
import os
import subprocess
import sys

HOME = os.path.expanduser("~")
HERE = os.path.dirname(os.path.abspath(__file__))
TEST = os.path.join(HERE, "test_gate_hooks_in_sync.py")
STATE_DIR = os.environ.get("NODE4_SYNC_STATE_DIR", HERE)
STATE = os.path.join(STATE_DIR, ".sync-test-mtimes.json")
EVENTS = os.path.join(STATE_DIR, ".sync-events.json")
SESSIONS_DIR = os.path.join(STATE_DIR, ".sync-sessions")
LOCK = os.path.join(STATE_DIR, ".sync-test.lock")
EVENTS_KEEP = 100
SESSION_TTL_SEC = 7 * 24 * 3600
ORCA_CLAUDE_PROFILES = os.path.join(os.environ.get("APPDATA", os.path.join(HOME, "AppData", "Roaming")),
                                    "orca", "claude-profiles")
WATCHED = [
    os.path.join(HOME, ".claude", "hooks", "node4-approval-gate.py"),
    os.path.join(HOME, ".gemini", "config", "hooks", "node4-approval-gate-agy.py"),
    os.path.join(HOME, ".codex", "hooks", "node4-approval-gate-codex.py"),
    TEST,
    # Claude 전역 settings.json (Orca 프로필들의 settings.json 은 watched_files 에서 glob)
    os.path.join(HOME, ".claude", "settings.json"),
    # agy·Gemini 훅 등록 파일
    os.path.join(HOME, ".gemini", "config", "hooks.json"),
    os.path.join(HOME, ".gemini", "settings.json"),
]
SUMMARY_MAX_CHARS = 1500


GEMINI_POLICY_DIR = os.path.join(HOME, ".gemini", "policies")
ORCA_CODEX_HOME = os.environ.get("NODE4_ORCA_CODEX_HOME") or os.path.join(
    os.environ.get("APPDATA", os.path.join(HOME, "AppData", "Roaming")), "orca",
    "codex-accounts", os.environ.get("ORCA_CODEX_ACCOUNT_ID", "<orca-codex-account-id>"), "home")
PIPELINE_MASTER = os.environ.get("NODE4_PIPELINE_MASTER", os.path.join(HOME, ".ai-global-pipeline.md"))  # 검증용 덮어쓰기
PIPELINE_SYNC = os.path.join(HERE, "sync_pipeline_rules.py")
WATCHED += [
    os.path.join(HERE, "sync_pipeline_rules.py"),
    os.path.join(HERE, "README.md"),  # 테스트 묶음 표·개수 검사 대상
    PIPELINE_MASTER,
    # 파이프라인 규칙 사본 (sync_pipeline_rules.TARGETS 와 같게 유지)
    os.path.join(HOME, ".claude", "CLAUDE.md"),
    os.path.join(HOME, ".gemini", "GEMINI.md"),
    os.path.join(HOME, ".codex", "AGENTS.md"),
    os.path.join(ORCA_CODEX_HOME, "AGENTS.md"),
    # Codex 전역·Orca 홈 hooks.json
    os.path.join(HOME, ".codex", "hooks.json"),
    os.path.join(ORCA_CODEX_HOME, "hooks.json"),
]


SKILLS_MASTER_DIR = os.path.join(HERE, "prompt-skills")
SKILLS_SYNC = os.path.join(HERE, "sync_prompt_skills.py")
SKILL_COPY_DIRS = [os.path.join(HOME, ".claude", "skills"), os.path.join(HOME, ".codex", "skills"),
                   os.path.join(ORCA_CODEX_HOME, "skills")]  # sync_prompt_skills.TARGET_DIRS 와 같게 유지
WATCHED.append(SKILLS_SYNC)


def skill_master_files() -> list:
    import glob
    return sorted(glob.glob(os.path.join(SKILLS_MASTER_DIR, "*", "SKILL.md")))


def watched_files() -> list:
    """감시 대상: 고정 목록 + Gemini 정책(*.toml) + Codex 규칙(전역 *.rules, Orca _orca-global-*.rules)
    + 프롬프트 스킬 마스터와 사본. glob 대상은 추가·삭제도 감지한다."""
    import glob
    masters = skill_master_files()
    names = [os.path.basename(os.path.dirname(p)) for p in masters]
    return WATCHED + masters + [os.path.join(d, n, "SKILL.md") for d in SKILL_COPY_DIRS for n in names] + sorted(
        glob.glob(os.path.join(ORCA_CLAUDE_PROFILES, "*", "home", "settings.json"))
        + glob.glob(os.path.join(GEMINI_POLICY_DIR, "*.toml"))
        + glob.glob(os.path.join(HOME, ".codex", "rules", "*.rules"))
        + glob.glob(os.path.join(ORCA_CODEX_HOME, "rules", "_orca-global-*.rules")))


def mtime(path: str):
    return os.path.getmtime(path) if os.path.exists(path) else None


def run_python(script: str, timeout: int):
    """python -I <script> 실행. (프로세스 결과, 출력 요약). 시간 초과면 결과가 None이다."""
    try:
        r = subprocess.run([sys.executable, "-I", script], capture_output=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        return None, f"[오류] {os.path.basename(script)} 가 {timeout}초 안에 끝나지 않았습니다(시간 초과)"
    return r, (r.stdout + r.stderr).decode("utf-8", errors="replace").strip()


def sync_pipeline_if_master_changed(previous) -> str:
    """마스터 수정 시각이 바뀌었으면 각 도구 규칙 파일 뒷부분을 갱신한다. 실행 결과 요약(없으면 '')."""
    if previous is None or previous.get(PIPELINE_MASTER) == mtime(PIPELINE_MASTER):
        return ""
    return run_python(PIPELINE_SYNC, 60)[1]


def sync_skills_if_master_changed(previous) -> str:
    """프롬프트 스킬 마스터가 바뀌었거나(추가 포함) 사본이 사라졌으면 사본을 갱신한다. 결과 요약(없으면 '')."""
    if previous is None:
        return ""
    masters = skill_master_files()
    changed = any(previous.get(p) != mtime(p) for p in masters)
    names = [os.path.basename(os.path.dirname(p)) for p in masters]
    # 폴더(또는 그 부모)가 실제로 있는 대상만 본다(Orca 없는 환경에서 항상 '없음'이 되는 것 방지)
    missing = any(not os.path.exists(os.path.join(d, n, "SKILL.md"))
                  for d in SKILL_COPY_DIRS if os.path.isdir(d) or os.path.isdir(os.path.dirname(d)) for n in names)
    if not (changed or missing):
        return ""
    return run_python(SKILLS_SYNC, 60)[1]


def current_mtimes() -> dict:
    return {p: (os.path.getmtime(p) if os.path.exists(p) else None) for p in watched_files()}


def failure_summary(output: str) -> str:
    """unittest 출력에서 실패 제목·오류 줄만 뽑아 짧게 만든다."""
    keep = [line for line in output.splitlines()
            if line.startswith(("FAIL:", "ERROR:", "AssertionError", "FAILED", "Ran "))
            or "Error:" in line]
    text = "\n".join(keep) or output[-SUMMARY_MAX_CHARS:]
    return text[:SUMMARY_MAX_CHARS]


def read_json(path: str, default):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default


def write_json(path: str, data) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = f"{path}.{os.getpid()}.tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False)
    os.replace(tmp, path)


class FileLock:
    """감지·테스트 구간을 한 프로세스만 돌게 한다. 오래된 잠금(비정상 종료)은 걷어 낸다."""
    # 잠금 안 최대 작업 시간 = 사본 갱신 60 + 60 + 테스트 120 = 240초. 그보다 길어야 실행 중인 잠금을 걷어 내지 않는다.
    WAIT_SEC, STALE_SEC = 140, 300

    def __enter__(self):
        import time
        deadline = time.time() + self.WAIT_SEC
        while True:
            try:
                self.fd = os.open(LOCK, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
                return self
            except FileExistsError:
                try:
                    if time.time() - os.path.getmtime(LOCK) > self.STALE_SEC:
                        os.remove(LOCK)
                        continue
                except OSError:
                    pass
                if time.time() > deadline:
                    raise TimeoutError("sync lock")
                time.sleep(0.05)

    def __exit__(self, *exc):
        os.close(self.fd)
        try:
            os.remove(LOCK)
        except OSError:
            pass


def detect_and_test() -> dict:
    """감시 파일이 바뀌었으면 (사본 갱신 →) 테스트를 돌리고 이벤트를 추가한다. 만든 이벤트(없으면 None)."""
    previous = read_json(STATE, None)
    synced = sync_pipeline_if_master_changed(previous)  # 갱신된 사본의 수정 시각까지 이번 상태에 담는다
    skills_synced = sync_skills_if_master_changed(previous)
    now = current_mtimes()
    if previous == now:
        return None
    if previous is None:  # 첫 실행: 현재 수정 시각만 기록
        write_json(STATE, now)
        return None
    # 상태 파일은 테스트·이벤트 기록이 끝난 뒤에 쓴다. 테스트 중 훅이 강제 종료돼도
    # 다음 호출이 같은 변경을 다시 검사하므로 실패가 사라지지 않는다.
    changed = [os.path.basename(p) for p in sorted(set(previous) | set(now)) if previous.get(p) != now.get(p)]
    result, test_output = run_python(TEST, 120)
    passed = result is not None and result.returncode == 0
    run_log(changed, passed, "\n".join(s for s in (synced, skills_synced) if s))
    event = {"ts": now_iso(), "detector": output_format(), "changed": changed, "passed": passed}
    notices = []
    if passed and pipeline_sync_changed(synced):  # 통과했어도 규칙 파일을 고쳤으면 알린다(막지는 않음)
        notices.append("[파이프라인 규칙 자동 갱신] 마스터(~/.ai-global-pipeline.md) 수정을 감지해 각 도구 규칙 파일 "
                       "뒷부분을 갱신했습니다. 동기화 테스트는 통과했습니다.\n" + synced
                       + "\n이미 실행 중인 세션은 새 규칙을 다시 읽지 않습니다. 새 세션부터 적용됩니다.")
    if passed and pipeline_sync_changed(skills_synced):
        notices.append("[프롬프트 스킬 자동 갱신] 마스터(~/.ai-gate/prompt-skills) 수정을 감지해 Claude·Codex 스킬 "
                       "사본을 갱신했습니다. 동기화 테스트는 통과했습니다.\n" + skills_synced)
    if notices:
        event["notice"] = "\n\n".join(notices)
        kinds = [k for k, on in (("파이프라인 규칙", pipeline_sync_changed(synced)),
                                 ("프롬프트 스킬", pipeline_sync_changed(skills_synced))) if on]
        event["notice_title"] = " · ".join(kinds) + " 사본을 마스터에 맞춰 자동 갱신했습니다."
    synced = "\n".join(s for s in (synced, skills_synced) if s)
    if not passed:
        output = test_output
        event["reason"] = ("[게이트 훅 동기화 테스트 실패] 수정된 파일: " + ", ".join(changed) + "\n"
                           + (f"규칙·스킬 자동 갱신 결과:\n{synced}\n" if synced else "")
                           + (output if result is None else failure_summary(output))
                           + "\n실패한 항목(게이트 훅 GATED·REDACTIONS / Claude·Codex 설정 / 파이프라인 규칙·프롬프트 스킬 사본 / "
                           + "README 테스트 표·개수)을 맞춘 뒤 다시 실행하세요: python "
                           + TEST.replace("\\", "/") + " -v")
    log = read_json(EVENTS, {"last_id": 0, "events": []})
    event["id"] = log["last_id"] + 1
    log = {"last_id": event["id"], "events": (log["events"] + [event])[-EVENTS_KEEP:]}
    write_json(EVENTS, log)
    write_json(STATE, now)  # 이벤트를 남긴 뒤에 상태를 확정한다
    return event


def session_key(payload) -> str:
    """도구 형식 + 세션 id. 파일 이름으로 쓸 수 있게 다듬는다. id 가 없으면 ''."""
    import re
    if not isinstance(payload, dict):
        return ""
    sid = next((str(payload[k]) for k in ("session_id", "sessionId", "conversationId", "conversation_id")
                if payload.get(k)), "")
    return (output_format() + "-" + re.sub(r"[^A-Za-z0-9_.-]", "_", sid))[:120] if sid else ""


def pending_for_session(key: str, created) -> list:
    """이 세션에 전달할 이벤트 목록을 정하고, 세션이 본 번호를 갱신한다."""
    log = read_json(EVENTS, {"last_id": 0, "events": []})
    own = [created] if created else []
    if not key:
        return own
    path = os.path.join(SESSIONS_DIR, key + ".json")
    seen = read_json(path, None)
    last_id = log["last_id"]
    if seen is None:  # 처음 보는 세션: 지난 이벤트는 건너뛰되, 지금 실패 상태거나 직접 만든 이벤트는 받는다
        latest = log["events"][-1] if log["events"] else None
        pending = own or ([latest] if latest and not latest["passed"] else [])
        prune_sessions()
    else:
        pending = [e for e in log["events"] if e["id"] > seen.get("seen", 0)]
    if seen is None or seen.get("seen") != last_id:
        write_json(path, {"seen": last_id, "ts": now_iso()})
    return pending


def prune_sessions() -> None:
    """오래 쓰지 않은 세션 파일을 정리한다(새 세션이 생길 때만)."""
    import glob
    import time
    for p in glob.glob(os.path.join(SESSIONS_DIR, "*.json")):
        try:
            if time.time() - os.path.getmtime(p) > SESSION_TTL_SEC:
                os.remove(p)
        except OSError:
            pass


def message_for(pending: list):
    """전달할 이벤트들로 출력 JSON 을 만든다. 알릴 것이 없으면 None."""
    if not pending:
        return None
    latest = pending[-1]
    notices = [e["notice"] for e in pending if e.get("notice")]
    if not latest["passed"]:
        return render(output_format(), "\n\n".join(notices + [latest["reason"]]))
    if notices:
        titles = list(dict.fromkeys(e["notice_title"] for e in pending if e.get("notice_title")))
        return render_notice(output_format(), "\n\n".join(notices), " ".join(titles))
    return None


def now_iso() -> str:
    import datetime
    return datetime.datetime.now().astimezone().isoformat(timespec="seconds")


def main() -> None:
    try:
        payload = json.loads(sys.stdin.read() or "{}")
    except Exception:
        payload = {}
    created = None
    # 빠른 경로: 바뀐 것이 없으면 잠그지 않는다(호출마다 도는 비용을 늘리지 않기 위해)
    previous = read_json(STATE, None)
    if previous != current_mtimes():  # 마스터도 감시 대상이라 여기서 함께 잡힌다
        with FileLock():
            created = detect_and_test()  # 잠근 뒤 다시 확인하므로 다른 프로세스가 먼저 처리했으면 None
    message = message_for(pending_for_session(session_key(payload), created))
    if message:
        print(json.dumps(message, ensure_ascii=True))


RUN_LOG = os.path.join(STATE_DIR, "sync-test-hook.log")


def run_log(changed: list, passed: bool, synced: str = "") -> None:
    """테스트를 실제로 돌린 경우만 한 줄 남긴다(어느 도구가 언제 감지했는지 추적용). 실패해도 무시."""
    try:
        import datetime
        entry = {"ts": datetime.datetime.now().astimezone().isoformat(timespec="seconds"),
                 "format": output_format(), "changed": changed, "passed": passed}
        if synced:
            entry["pipeline_sync"] = synced.splitlines()
        with open(RUN_LOG, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except Exception:
        pass


def output_format() -> str:
    args = sys.argv[1:]
    if "--format" in args and args.index("--format") + 1 < len(args):
        return args[args.index("--format") + 1]
    return "claude"


def pipeline_sync_changed(synced: str) -> bool:
    """동기화 스크립트가 실제로 파일을 고쳤거나 오류를 냈는지('[같음]'만이면 알릴 필요 없음)."""
    return any(line.startswith(("[갱신]", "[오류]", "[다름]")) or not line.startswith("[")
               for line in synced.splitlines() if line.strip())


def render_notice(fmt: str, text: str, title: str = "") -> dict:
    """막지 않는 알림. 에이전트 문맥에 넣고, 지원하는 도구는 사용자 화면에도 한 줄 띄운다."""
    if fmt == "agy":
        return {"injectSteps": [{"ephemeralMessage": text}], "terminationBehavior": ""}
    event = "AfterTool" if fmt == "gemini" else "PostToolUse"
    return {"hookSpecificOutput": {"hookEventName": event, "additionalContext": text},
            "systemMessage": title or "사본을 마스터에 맞춰 자동 갱신했습니다."}


def render(fmt: str, reason: str) -> dict:
    """도구별 사후 훅 출력 형식으로 실패 알림을 만든다."""
    if fmt == "gemini":
        return {"hookSpecificOutput": {"hookEventName": "AfterTool", "additionalContext": reason},
                "systemMessage": "게이트 훅 동기화 테스트 실패 - 세 훅 정의가 어긋났습니다."}
    if fmt == "agy":
        return {"injectSteps": [{"ephemeralMessage": reason}], "terminationBehavior": ""}
    # claude / codex
    return {"decision": "block", "reason": reason,
            "hookSpecificOutput": {"hookEventName": "PostToolUse", "additionalContext": reason}}


if __name__ == "__main__":
    try:
        main()
    except Exception:
        pass
