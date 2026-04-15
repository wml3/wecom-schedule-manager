#!/usr/bin/env python
"""
安全发布 GitHub 版本的脚本。

目标：
1. 规避 Windows / PowerShell 中文编码问题
2. 规避本地失效代理环境变量对 git push 的影响
3. 自动创建/更新 tag、release 和 release note

推荐用法：
    python scripts/publish_github_release.py \
        --version v1.0.2 \
        --notes-file assets/release-notes/release-note-template.md
"""

from __future__ import annotations

import argparse
import base64
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Dict, Optional, Tuple

import requests


PROXY_ENV_NAMES = (
    "HTTP_PROXY",
    "HTTPS_PROXY",
    "ALL_PROXY",
    "NO_PROXY",
    "http_proxy",
    "https_proxy",
    "all_proxy",
    "no_proxy",
    "GIT_HTTP_PROXY",
    "GIT_HTTPS_PROXY",
)


def configure_stdio() -> None:
    for stream_name in ("stdout", "stderr"):
        stream = getattr(sys, stream_name, None)
        if stream and hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="发布 GitHub tag 和 release，避免中文 release note 乱码。")
    parser.add_argument("--version", required=True, help="版本号，例如 v1.0.2")
    parser.add_argument("--notes-file", help="UTF-8 release note 文件路径，推荐使用。")
    parser.add_argument("--notes-stdin", action="store_true", help="从标准输入读取 UTF-8 release note。")
    parser.add_argument("--repo", help="GitHub 仓库，格式 owner/repo。默认从 git remote origin 自动解析。")
    parser.add_argument("--remote", default="origin", help="git remote 名称，默认 origin。")
    parser.add_argument("--target", default="main", help="目标分支，默认 main。")
    parser.add_argument("--release-name", help="Release 名称。默认与版本号相同。")
    parser.add_argument("--tag-message", help="Annotated tag 的说明。默认自动生成。")
    parser.add_argument("--draft", action="store_true", help="是否创建为草稿 release。")
    parser.add_argument("--prerelease", action="store_true", help="是否标记为 prerelease。")
    parser.add_argument(
        "--force-tag",
        action="store_true",
        help="当本地 tag 已存在但不指向当前 HEAD 时，允许强制重建并覆盖远端 tag。",
    )
    return parser.parse_args()


def sanitized_env() -> Dict[str, str]:
    env = os.environ.copy()
    for name in PROXY_ENV_NAMES:
        env.pop(name, None)
    return env


def run_git(*args: str, cwd: Path, env: Dict[str, str], check: bool = True) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(
        ["git", *args],
        cwd=str(cwd),
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    if check and result.returncode != 0:
        raise SystemExit(
            "git 命令执行失败：\n"
            f"git {' '.join(args)}\n"
            f"stdout:\n{result.stdout}\n"
            f"stderr:\n{result.stderr}"
        )
    return result


def get_repo_root(env: Dict[str, str]) -> Path:
    result = run_git("rev-parse", "--show-toplevel", cwd=Path.cwd(), env=env)
    return Path(result.stdout.strip())


def get_head_sha(repo_root: Path, env: Dict[str, str]) -> str:
    return run_git("rev-parse", "HEAD", cwd=repo_root, env=env).stdout.strip()


def get_remote_url(repo_root: Path, remote: str, env: Dict[str, str]) -> str:
    return run_git("remote", "get-url", remote, cwd=repo_root, env=env).stdout.strip()


def parse_github_repo(remote_url: str) -> Tuple[str, str]:
    patterns = [
        r"^https://github\.com/([^/]+)/([^/.]+?)(?:\.git)?$",
        r"^git@github\.com:([^/]+)/([^/.]+?)(?:\.git)?$",
        r"^ssh://git@github\.com/([^/]+)/([^/.]+?)(?:\.git)?$",
    ]
    for pattern in patterns:
        match = re.match(pattern, remote_url)
        if match:
            return match.group(1), match.group(2)
    raise SystemExit(f"无法从 git remote 解析 GitHub 仓库地址：{remote_url}")


def read_notes(args: argparse.Namespace) -> str:
    if args.notes_file:
        return Path(args.notes_file).read_text(encoding="utf-8-sig").strip()
    if args.notes_stdin:
        return sys.stdin.read().strip()
    raise SystemExit("请提供 --notes-file 或 --notes-stdin。为了避免乱码，推荐使用 --notes-file。")


def git_auth_configs(token: str) -> list[str]:
    pair = f"x-access-token:{token}"
    basic = base64.b64encode(pair.encode("ascii")).decode("ascii")
    return [
        "-c",
        "http.version=HTTP/1.1",
        "-c",
        f"http.extraheader=AUTHORIZATION: basic {basic}",
    ]


def local_tag_commit(tag_name: str, repo_root: Path, env: Dict[str, str]) -> Optional[str]:
    result = run_git("tag", "--list", tag_name, cwd=repo_root, env=env, check=False)
    if not result.stdout.strip():
        return None
    return run_git("rev-list", "-n", "1", tag_name, cwd=repo_root, env=env).stdout.strip()


def ensure_local_tag(
    tag_name: str,
    head_sha: str,
    repo_root: Path,
    env: Dict[str, str],
    tag_message: str,
    force_tag: bool,
) -> None:
    current_tag_commit = local_tag_commit(tag_name, repo_root, env)
    if current_tag_commit is None:
        run_git("tag", "-a", tag_name, "-m", tag_message, cwd=repo_root, env=env)
        return
    if current_tag_commit == head_sha:
        return
    if not force_tag:
        raise SystemExit(
            f"本地 tag {tag_name} 已存在，但它指向 {current_tag_commit}，当前 HEAD 是 {head_sha}。"
            " 如需覆盖，请加 --force-tag。"
        )
    run_git("tag", "-d", tag_name, cwd=repo_root, env=env)
    run_git("tag", "-a", tag_name, "-m", tag_message, cwd=repo_root, env=env)


def git_push_ref(
    repo_root: Path,
    env: Dict[str, str],
    token: str,
    remote: str,
    refspec: str,
    force: bool = False,
) -> bool:
    args = [*git_auth_configs(token), "push"]
    if force:
        args.append("--force")
    args.extend([remote, refspec])
    result = run_git(*args, cwd=repo_root, env=env, check=False)
    if result.returncode == 0:
        return True
    print(
        "git push 失败，将尝试用 GitHub API 兜底：\n"
        f"git {' '.join(args)}\n"
        f"stderr:\n{result.stderr}",
        file=sys.stderr,
    )
    return False


def github_session(token: str) -> requests.Session:
    session = requests.Session()
    session.headers.update(
        {
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "Content-Type": "application/json; charset=utf-8",
        }
    )
    for name in PROXY_ENV_NAMES:
        session.trust_env = False
    return session


def ensure_remote_branch(session: requests.Session, repo: str, branch: str, head_sha: str) -> str:
    response = session.get(f"https://api.github.com/repos/{repo}/branches/{branch}", timeout=30)
    response.raise_for_status()
    current_sha = response.json()["commit"]["sha"]
    if current_sha == head_sha:
        return current_sha
    patch = session.patch(
        f"https://api.github.com/repos/{repo}/git/refs/heads/{branch}",
        json={"sha": head_sha, "force": False},
        timeout=30,
    )
    patch.raise_for_status()
    return patch.json()["object"]["sha"]


def ensure_release(
    session: requests.Session,
    repo: str,
    *,
    version: str,
    target: str,
    release_name: str,
    body: str,
    draft: bool,
    prerelease: bool,
) -> str:
    payload = {
        "tag_name": version,
        "target_commitish": target,
        "name": release_name,
        "body": body,
        "draft": draft,
        "prerelease": prerelease,
    }
    response = session.get(f"https://api.github.com/repos/{repo}/releases/tags/{version}", timeout=30)
    if response.status_code == 404:
        created = session.post(f"https://api.github.com/repos/{repo}/releases", json=payload, timeout=30)
        created.raise_for_status()
        return created.json()["html_url"]
    response.raise_for_status()
    release_id = response.json()["id"]
    updated = session.patch(f"https://api.github.com/repos/{repo}/releases/{release_id}", json=payload, timeout=30)
    updated.raise_for_status()
    return updated.json()["html_url"]


def main() -> int:
    configure_stdio()
    args = parse_args()
    env = sanitized_env()
    repo_root = get_repo_root(env)
    token = os.getenv("GITHUB_TOKEN")
    if not token:
        raise SystemExit("缺少环境变量 GITHUB_TOKEN。")

    if args.repo:
        repo = args.repo
    else:
        owner, name = parse_github_repo(get_remote_url(repo_root, args.remote, env))
        repo = f"{owner}/{name}"

    version = args.version.strip()
    release_name = args.release_name or version
    notes = read_notes(args)
    head_sha = get_head_sha(repo_root, env)
    tag_message = args.tag_message or f"Release {version}"

    ensure_local_tag(version, head_sha, repo_root, env, tag_message=tag_message, force_tag=args.force_tag)

    tag_push_ok = git_push_ref(
        repo_root=repo_root,
        env=env,
        token=token,
        remote=args.remote,
        refspec=f"refs/tags/{version}",
        force=args.force_tag,
    )
    branch_push_ok = git_push_ref(
        repo_root=repo_root,
        env=env,
        token=token,
        remote=args.remote,
        refspec=args.target,
        force=False,
    )

    session = github_session(token)
    remote_branch_sha = ensure_remote_branch(session, repo, args.target, head_sha)
    release_url = ensure_release(
        session,
        repo,
        version=version,
        target=args.target,
        release_name=release_name,
        body=notes,
        draft=args.draft,
        prerelease=args.prerelease,
    )

    print(
        f"发布完成：\n"
        f"- repo: {repo}\n"
        f"- version: {version}\n"
        f"- local_head: {head_sha}\n"
        f"- remote_branch: {args.target}\n"
        f"- remote_branch_sha: {remote_branch_sha}\n"
        f"- tag_push_ok: {tag_push_ok}\n"
        f"- branch_push_ok: {branch_push_ok}\n"
        f"- release_url: {release_url}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
