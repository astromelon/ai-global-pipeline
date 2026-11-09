"""프롬프트 스킬 마스터(~/.ai-gate/prompt-skills/<이름>/SKILL.md)를 Claude·Codex 스킬 폴더에 복사한다.

사용:
  python sync_prompt_skills.py          # 다른 사본만 갱신
  python sync_prompt_skills.py --check  # 쓰지 않고 검사만. 다르면 종료 코드 1

대상:
  ~/.claude/skills/<이름>/SKILL.md   (Orca Claude 프로필의 skills 는 이 폴더를 가리키는 링크라 함께 적용된다)
  ~/.codex/skills/<이름>/SKILL.md
  Orca Codex 홈 skills/<이름>/SKILL.md
마스터에 없는 스킬은 대상에서 지우지 않는다(다른 스킬과 섞여 있으므로). 이름을 바꾸면 옛 폴더는 직접 지운다.
sync_test_hook.py 가 마스터 수정 시각이 바뀌면 이 스크립트를 자동으로 실행한다.
"""
import glob
import os
import sys

HOME = os.path.expanduser("~")
APPDATA = os.environ.get("APPDATA", os.path.join(HOME, "AppData", "Roaming"))
HERE = os.path.dirname(os.path.abspath(__file__))
MASTER_DIR = os.environ.get("NODE4_PROMPT_SKILLS_MASTER", os.path.join(HERE, "prompt-skills"))
TARGET_DIRS = [
    os.path.join(HOME, ".claude", "skills"),
    os.path.join(HOME, ".codex", "skills"),
    os.path.join(APPDATA, "orca", "codex-accounts", os.environ.get("ORCA_CODEX_ACCOUNT_ID", "<orca-codex-account-id>"), "home", "skills"),
]
if os.environ.get("NODE4_PROMPT_SKILLS_TARGETS"):  # 검증용 덮어쓰기 (os.pathsep 구분)
    TARGET_DIRS = os.environ["NODE4_PROMPT_SKILLS_TARGETS"].split(os.pathsep)


def read(path: str) -> bytes:
    with open(path, "rb") as f:
        return f.read()


def master_files() -> list:
    """마스터 SKILL.md 경로 목록(이름순)."""
    return sorted(glob.glob(os.path.join(MASTER_DIR, "*", "SKILL.md")))


def plan() -> list:
    """(대상 경로, 상태, 마스터 내용) 목록. 상태: same / update / missing."""
    result = []
    for src in master_files():
        name = os.path.basename(os.path.dirname(src))
        body = read(src)
        for root in TARGET_DIRS:
            dst = os.path.join(root, name, "SKILL.md")
            if not os.path.exists(dst):
                state = "missing"
            else:
                state = "same" if read(dst) == body else "update"
            result.append((dst, state, body))
    return result


def main() -> int:
    check_only = "--check" in sys.argv[1:]
    if not master_files():
        print(f"마스터 스킬이 없습니다: {MASTER_DIR}")
        return 2
    failed = False
    for dst, state, body in plan():
        if state == "same":
            print(f"[같음] {dst}")
        elif check_only:
            failed = True
            print(f"[{'없음' if state == 'missing' else '다름'}] {dst}")
        else:
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            tmp = dst + ".sync-tmp"
            with open(tmp, "wb") as f:
                f.write(body)
            os.replace(tmp, dst)
            print(f"[갱신] {dst}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.exit(main())
