"""Claude settings 의 permissions.allow 중 Node 4 게이트 대상 명령까지 허용하는 규칙을 찾는다.

훅과 전역 ask 규칙이 먼저 걸려 평소에는 확인창이 뜨지만, 훅이 실패하면 이 allow 규칙 때문에
확인 없이 실행될 수 있다. '항상 허용'을 누르다 쌓이기 쉬우므로 가끔 점검한다.

사용: python scan_allow_overlap.py [--fix]   (--fix: 겹치는 규칙을 지우고 ~/.ai-gate/allow-backups/ 에 원본 백업)
대상: 전역·Orca 프로필 settings.json, C:\\workspace·C:\\dev 아래 각 저장소의 .claude/settings(.local).json
"""
import datetime
import glob
import importlib.util
import json
import os
import re
import shutil
import sys

HOME = os.path.expanduser("~")
BACKUP_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "allow-backups")
# 게이트에 걸려야 하는 대표 명령. allow 규칙이 이 중 하나라도 허용하면 겹친다고 본다.
GATED_SAMPLES = ["git push origin main", "git merge feat/x", "git rebase origin/main", "git reset --hard HEAD",
                 "git clean -fd", "git branch -D feat/x", "git checkout -- a.txt", "git checkout .",
                 "git checkout -f main", "git restore a.txt", "git stash drop", "git stash clear",
                 "glab mr merge 1", "rm a.txt", "rm -rf build", "Remove-Item a.txt", "del a.txt", "rmdir build"]


def settings_files() -> list:
    files = [os.path.join(HOME, ".claude", "settings.json")]
    files += glob.glob(os.path.join(os.environ.get("APPDATA", ""), "orca", "claude-profiles", "*", "home", "settings.json"))
    for root in (r"C:\workspace", r"C:\dev"):
        for name in ("settings.json", "settings.local.json"):
            files += glob.glob(os.path.join(root, "*", ".claude", name))
            files += glob.glob(os.path.join(root, "*", "*", ".claude", name))
    return sorted({os.path.normpath(f) for f in files if os.path.isfile(f)})


def rule_allows(rule: str, command: str) -> bool:
    """Claude 권한 규칙 Tool(패턴) 이 명령을 허용하는지(Bash/PowerShell 만, '*' 와일드카드·':*' 접두 표기 지원)."""
    m = re.fullmatch(r"(Bash|PowerShell)(?:\((.*)\))?", rule.strip(), re.DOTALL)
    if not m:
        return False
    pattern = m.group(2)
    if pattern is None or pattern.strip() in ("", "*"):
        return True  # 도구 전체 허용
    pattern = re.sub(r":\*$", " *", pattern.strip())
    regex = "^" + ".*".join(re.escape(part) for part in pattern.split("*")) + "$"
    if pattern.endswith(" *") and re.fullmatch(regex[:-len(re.escape(" ") + ".*$")] + "$", command):
        return True  # 'git push *' 는 인자 없는 'git push' 도 허용
    return re.match(regex, command) is not None


def overlaps(rule: str) -> list:
    return [c for c in GATED_SAMPLES if rule_allows(rule, c)]


def main() -> int:
    fix = "--fix" in sys.argv[1:]
    found = 0
    for path in settings_files():
        try:
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
        except Exception as e:
            print(f"[읽기 실패] {path}: {e}")
            continue
        allow = (data.get("permissions") or {}).get("allow") or []
        bad = [(r, overlaps(r)) for r in allow if overlaps(r)]
        if not bad:
            continue
        found += len(bad)
        print(path)
        for rule, hits in bad:
            print(f"  - {rule}   ← {', '.join(hits[:4])}{' …' if len(hits) > 4 else ''}")
        if fix:
            stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
            # 저장소 안에 백업을 두면 git 미추적 파일로 보이므로 이 폴더 아래에 둔다
            backup = os.path.join(BACKUP_DIR, re.sub(r"[:\\/]+", "_", path).strip("_") + f".bak-allow-{stamp}")
            os.makedirs(BACKUP_DIR, exist_ok=True)
            shutil.copy2(path, backup)
            data["permissions"]["allow"] = [r for r in allow if not overlaps(r)]
            with open(path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
                f.write("\n")
            print(f"  → {len(bad)}개 제거, 백업 {backup}")
    print(f"\n겹치는 allow 규칙: {found}개" + ("" if fix or not found else " (지우려면 --fix)"))
    return 1 if found and not fix else 0


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.exit(main())
