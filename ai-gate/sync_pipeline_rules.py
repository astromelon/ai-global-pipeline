"""마스터 파이프라인 규칙(~/.ai-global-pipeline.md)을 각 도구의 전역 규칙 파일 뒷부분에 반영한다.

사용:
  python sync_pipeline_rules.py          # 다른 사본만 갱신(갱신 전 <파일>.bak-pipeline-sync 로 1개 백업, 매번 덮어씀)
  python sync_pipeline_rules.py --check  # 쓰지 않고 검사만. 다르면 종료 코드 1

규칙: 각 대상 파일에서 줄 머리의 '# Global Maintenance Pipeline' 제목부터 파일 끝까지를 마스터로 바꾼다.
제목 앞부분(CLAUDE.md 의 기존 규칙, Orca Codex AGENTS.md 의 DDIA 등)은 그대로 둔다.
제목이 없거나 2개 이상인 파일은 건드리지 않고 오류로 보고한다(어디까지가 파이프라인인지 알 수 없으므로).
sync_test_hook.py 가 마스터 수정 시각이 바뀌면 이 스크립트를 자동으로 실행한다.
"""
import os
import re
import shutil
import sys

HOME = os.path.expanduser("~")
APPDATA = os.environ.get("APPDATA", os.path.join(HOME, "AppData", "Roaming"))
MASTER = os.environ.get("NODE4_PIPELINE_MASTER", os.path.join(HOME, ".ai-global-pipeline.md"))
TARGETS = [
    os.path.join(HOME, ".claude", "CLAUDE.md"),
    os.path.join(HOME, ".gemini", "GEMINI.md"),
    os.path.join(HOME, ".codex", "AGENTS.md"),
    os.path.join(APPDATA, "orca", "codex-accounts", os.environ.get("ORCA_CODEX_ACCOUNT_ID", "<orca-codex-account-id>"), "home", "AGENTS.md"),
]
if os.environ.get("NODE4_PIPELINE_TARGETS"):  # 검증용 덮어쓰기 (os.pathsep 구분)
    TARGETS = os.environ["NODE4_PIPELINE_TARGETS"].split(os.pathsep)
HEADING = re.compile(r"^# Global Maintenance Pipeline\b", re.MULTILINE)


def read(path: str) -> str:
    with open(path, encoding="utf-8", newline="") as f:
        return f.read()


def expected(target_text: str, master: str) -> str:
    """대상 파일이 가져야 할 내용. 제목 위치를 확정할 수 없으면 ValueError."""
    marks = list(HEADING.finditer(target_text))
    if len(marks) != 1:
        raise ValueError(f"'# Global Maintenance Pipeline' 제목이 {len(marks)}개입니다(1개여야 함)")
    newline = "\r\n" if "\r\n" in target_text else "\n"
    body = master.replace("\r\n", "\n").rstrip("\n") + "\n"
    return target_text[:marks[0].start()] + body.replace("\n", newline)


def plan(master: str) -> list:
    """(대상, 상태, 새 내용 또는 오류) 목록. 상태: same / update / error."""
    result = []
    for target in TARGETS:
        try:
            current = read(target)
            new = expected(current, master)
            result.append((target, "same" if new == current else "update", new))
        except (OSError, ValueError) as e:
            result.append((target, "error", str(e)))
    return result


def main() -> int:
    check_only = "--check" in sys.argv[1:]
    master = read(MASTER)
    if not HEADING.match(master):
        print(f"마스터가 '# Global Maintenance Pipeline' 제목으로 시작하지 않습니다: {MASTER}")
        return 2
    failed = False
    for target, state, payload in plan(master):
        if state == "error":
            failed = True
            print(f"[오류] {target}: {payload}")
        elif state == "same":
            print(f"[같음] {target}")
        elif check_only:
            failed = True
            print(f"[다름] {target}")
        else:
            shutil.copy2(target, target + ".bak-pipeline-sync")
            tmp = target + ".pipeline-sync-tmp"
            with open(tmp, "w", encoding="utf-8", newline="") as f:
                f.write(payload)
            os.replace(tmp, target)
            print(f"[갱신] {target}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.exit(main())
