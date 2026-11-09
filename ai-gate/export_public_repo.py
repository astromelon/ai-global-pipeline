"""실제 설정(~/.ai-gate, ~/.claude 등)을 공개 저장소 폴더로 내보낸다. 경로·계정 ID·사내 고유 값은 자리표시자로 바꾼다.

사용:
  python export_public_repo.py                 # 임시 폴더에 만들고 → 유출 검사 → 통과하면 저장소에 복사
  python export_public_repo.py --check         # 쓰지 않고 저장소와 다른 파일만 보고. 다르면 종료 코드 1
  python export_public_repo.py --test          # 복사 후 저장소 사본으로 동기화 테스트도 실행
  python export_public_repo.py --repo D:/path  # 저장소 위치(기본 C:/dev/ai-global-pipeline)

하지 않는 것: 커밋·push·파일 삭제. 원본에서 사라져 저장소에만 남은 파일은 목록만 보여 준다(직접 git rm).

자리표시자 규칙
- 홈 경로(이 PC의 Path.home())는 Python 문자열이면 os.path.expanduser(r"~\\..."), JSON 이면 C:/Users/<you>/, README 는 $HOME/ 또는 ~
- Orca Codex 계정 id 는 ORCA_CODEX_ACCOUNT_ID 환경변수, Orca Claude 프로필 id 는 <orca-claude-profile-id>
- 그 밖의 사내 고유 값은 이 스크립트에 적지 않고 비공개 파일 export-private.json 에 둔다(이 파일은 내보내지 않는다):
    {"replacements": {"원래 문자열": "바꿀 문자열", ...}, "forbidden": ["결과에 남으면 안 되는 단어", ...]}
결과에 홈 사용자명·계정 id·forbidden 단어·토큰 형태 문자열이 남으면 저장소에 쓰지 않고 실패한다.
"""
import argparse
import glob
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

HOME = Path.home()
HERE = Path(__file__).resolve().parent
APPDATA = Path(os.environ.get("APPDATA", HOME / "AppData" / "Roaming"))
DEFAULT_REPO = Path(os.environ.get("AI_PIPELINE_PUBLIC_REPO", r"C:\dev\ai-global-pipeline"))
PRIVATE = HERE / "export-private.json"
ENV_ID = 'os.environ.get("ORCA_CODEX_ACCOUNT_ID", "<orca-codex-account-id>")'
# 저장소에서 이 스크립트가 관리하지 않는 파일(손으로 쓰는 문서 등). --check 의 "저장소에만 있음"에서 뺀다.
UNMANAGED = {".gitignore", "README.md", "LICENSE"}

# 저장소 경로 → 원본
FILES = {
    "pipeline/ai-global-pipeline.md": HOME / ".ai-global-pipeline.md",
    "hooks/claude/node4-approval-gate.py": HOME / ".claude/hooks/node4-approval-gate.py",
    "hooks/agy/node4-approval-gate-agy.py": HOME / ".gemini/config/hooks/node4-approval-gate-agy.py",
    "hooks/codex/node4-approval-gate-codex.py": HOME / ".codex/hooks/node4-approval-gate-codex.py",
    "config/gemini/ai-global-pipeline.toml": HOME / ".gemini/policies/ai-global-pipeline.toml",
    "config/codex/default.rules": HOME / ".codex/rules/default.rules",
    "config/codex/hooks.json": HOME / ".codex/hooks.json",
    "config/agy/hooks.json": HOME / ".gemini/config/hooks.json",
}
for _name in ("README.md", "bench_sync_hook.py", "gate_report.py", "scan_allow_overlap.py", "sync_pipeline_rules.py",
              "sync_prompt_skills.py", "sync_test_hook.py", "test_gate_hooks_in_sync.py", "export_public_repo.py"):
    FILES["ai-gate/" + _name] = HERE / _name
for _skill in sorted((HERE / "prompt-skills").glob("*/SKILL.md")):
    FILES[f"ai-gate/prompt-skills/{_skill.parent.name}/SKILL.md"] = _skill

TOKEN_PATTERNS = [r"gh[pousr]_[A-Za-z0-9]{20,}", r"glpat-[A-Za-z0-9_-]{20,}", r"sk-[A-Za-z0-9_-]{20,}",
                  r"AKIA[0-9A-Z]{16}", r"xox[baprs]-[A-Za-z0-9-]{10,}", r"-----BEGIN [A-Z ]*PRIVATE KEY-----"]


def load_private() -> dict:
    if not PRIVATE.exists():
        return {"replacements": {}, "forbidden": []}
    data = json.loads(PRIVATE.read_text(encoding="utf-8"))
    return {"replacements": data.get("replacements", {}), "forbidden": data.get("forbidden", [])}


def account_ids() -> tuple:
    codex = [Path(p).name for p in glob.glob(str(APPDATA / "orca" / "codex-accounts" / "*"))]
    claude = [Path(p).name for p in glob.glob(str(APPDATA / "orca" / "claude-profiles" / "*"))]
    return codex, claude


def home_forms() -> dict:
    win = str(HOME)                       # C:\Users\name
    fwd = win.replace("\\", "/")          # C:/Users/name
    msys = "/" + fwd[0].lower() + fwd[2:]  # /c/Users/name
    return {"win": win, "fwd": fwd, "msys": msys}


def sanitize(rel: str, text: str, private: dict) -> str:
    h = home_forms()
    codex_ids, claude_ids = account_ids()
    for old, new in private["replacements"].items():
        text = text.replace(old, new)
    if rel.endswith(".py"):
        for cid in codex_ids:  # 원시 문자열 경로 속 계정 id → 환경변수
            text = re.sub(r'r"' + re.escape(h["win"]) + r'\\([^"]*?)\\' + re.escape(cid) + r'\\([^"]*)"',
                          lambda m: f'os.path.join(os.path.expanduser(r"~\\{m.group(1)}"), {ENV_ID}, r"{m.group(2)}")',
                          text)
            text = text.replace(f'"{cid}"', ENV_ID)
        text = re.sub(r'r"' + re.escape(h["win"]) + r'\\([^"]*)"',
                      lambda m: f'os.path.expanduser(r"~\\{m.group(1)}")', text)
        text = text.replace(h["fwd"] + "/", "~/")
    elif rel.endswith(".json"):
        text = text.replace(h["fwd"] + "/", "C:/Users/<you>/")
        text = text.replace(h["win"].replace("\\", "\\\\"), "C:\\\\Users\\\\<you>")
    else:
        text = text.replace(h["fwd"] + "/", "$HOME/").replace(h["win"], "~").replace(h["msys"], "~")
    for cid in codex_ids:
        text = text.replace(cid, "<orca-codex-account-id>")
    for pid in claude_ids:
        text = text.replace(pid, "<orca-claude-profile-id>")
    return text


def snippets() -> dict:
    """설정 파일에서 게이트 관련 부분만 뽑는다(인증·개인 허용 목록 제외)."""
    def load(p):
        return json.loads((HOME / p).read_text(encoding="utf-8"))
    c = load(".claude/settings.json")
    perm = c.get("permissions", {})
    a = load(".gemini/antigravity-cli/settings.json")
    g = load(".gemini/settings.json")
    data = {
        "config/claude/settings.gate-snippet.json":
            {"permissions": {k: perm[k] for k in ("ask", "deny") if perm.get(k)}, "hooks": c.get("hooks")},
        "config/agy/settings.deny-snippet.json": {"permissions": {"deny": a.get("permissions", {}).get("deny")}},
        "config/gemini/settings.hooks-snippet.json": {"hooks": g.get("hooks")},
    }
    return {rel: json.dumps(obj, ensure_ascii=False, indent=2) + "\n" for rel, obj in data.items()}


def build(private: dict) -> dict:
    out = {}
    for rel, src in FILES.items():
        out[rel] = sanitize(rel, src.read_text(encoding="utf-8"), private)
    for rel, text in snippets().items():
        out[rel] = sanitize(rel, text, private)
    return out


def leaks(files: dict, private: dict) -> list:
    codex_ids, claude_ids = account_ids()
    words = [HOME.name] + codex_ids + claude_ids + private["forbidden"]
    pattern = re.compile("|".join([re.escape(w) for w in words if w] + TOKEN_PATTERNS), re.IGNORECASE)
    found = []
    for rel, text in files.items():
        for no, line in enumerate(text.splitlines(), 1):
            m = pattern.search(line)
            if m:
                found.append(f"{rel}:{no}: '{m.group(0)}'")
    return found


def normalize(text: str) -> str:
    return text.replace("\r\n", "\n")


def compare(repo: Path, files: dict) -> tuple:
    changed = [rel for rel, text in files.items()
               if not (repo / rel).exists() or normalize((repo / rel).read_text(encoding="utf-8")) != normalize(text)]
    managed_dirs = {"pipeline", "hooks", "config", "ai-gate"}
    existing = {p.relative_to(repo).as_posix() for p in repo.rglob("*")
                if p.is_file() and ".git" not in p.relative_to(repo).parts and "__pycache__" not in p.parts}
    stale = sorted(rel for rel in existing - set(files)
                   if rel not in UNMANAGED and rel.split("/", 1)[0] in managed_dirs)
    return changed, stale


def run_tests(repo: Path) -> int:
    env = dict(os.environ)
    codex_ids, _ = account_ids()
    if codex_ids and "ORCA_CODEX_ACCOUNT_ID" not in env:
        env["ORCA_CODEX_ACCOUNT_ID"] = codex_ids[0]
    return subprocess.run([sys.executable, "-B", str(repo / "ai-gate" / "test_gate_hooks_in_sync.py")], env=env).returncode


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", type=Path, default=DEFAULT_REPO)
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--test", action="store_true")
    args = ap.parse_args()
    if not (args.repo / ".git").exists():
        print(f"저장소가 아닙니다: {args.repo}")
        return 2

    private = load_private()
    files = build(private)
    found = leaks(files, private)
    if found:
        print("[중단] 공개하면 안 되는 값이 남았습니다. 자리표시자 규칙이나 export-private.json 을 고치세요:")
        print("\n".join("  " + f for f in found))
        return 3

    changed, stale = compare(args.repo, files)
    for rel in changed:
        print(f"[{'다름' if args.check else '갱신'}] {rel}")
    for rel in stale:
        print(f"[저장소에만 있음] {rel}  (원본에서 사라졌으면 git rm 으로 지운다)")
    if not changed:
        print("변경 없음")
    if args.check:
        return 1 if changed else 0

    with tempfile.TemporaryDirectory() as tmp:  # 모두 만든 뒤 한꺼번에 옮긴다
        for rel in changed:
            dst = Path(tmp) / rel
            dst.parent.mkdir(parents=True, exist_ok=True)
            dst.write_text(files[rel], encoding="utf-8", newline="\n")
        for rel in changed:
            target = args.repo / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(Path(tmp) / rel, target)

    if args.test:
        code = run_tests(args.repo)
        print("저장소 사본 동기화 테스트:", "통과" if code == 0 else f"실패(종료 코드 {code})")
        if code:
            return 4
    if changed:
        print(f"\n다음: cd {args.repo} && git diff 로 확인 후 커밋·push")
    return 0


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.exit(main())
