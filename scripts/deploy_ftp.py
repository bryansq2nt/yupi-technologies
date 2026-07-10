#!/usr/bin/env python3
"""Deploy the YupiTech static site over FTP/FTPS."""
from __future__ import annotations

import argparse
import datetime as dt
import fnmatch
import ftplib
import getpass
import os
import posixpath
from dataclasses import dataclass
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_ENV_FILE = ROOT / ".deploy.env"


@dataclass(frozen=True)
class Config:
    host: str
    port: int
    username: str
    password: str
    remote_dir: str
    local_dir: Path
    use_tls: bool
    timeout: int
    excludes: tuple[str, ...]
    protected_paths: tuple[str, ...]


def parse_env_file(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if not path.exists():
        return values

    for line_number, raw_line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[len("export ") :].strip()
        if "=" not in line:
            raise ValueError(f"{path}:{line_number}: expected KEY=value")

        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
            value = value[1:-1]
        values[key] = value
    return values


def env_value(values: dict[str, str], key: str, default: str = "") -> str:
    return os.environ.get(key, values.get(key, default))


def bool_value(value: str) -> bool:
    return value.strip().lower() not in {"0", "false", "no", "off"}


def csv(value: str) -> tuple[str, ...]:
    return tuple(part.strip() for part in value.split(",") if part.strip())


def load_config(args: argparse.Namespace) -> Config:
    env_path = Path(args.env_file).expanduser()
    values = parse_env_file(env_path)

    host = args.host or env_value(values, "FTP_HOST", "ftp.mutechlabs.com")
    username = args.username or env_value(values, "FTP_USERNAME", "admin@mutechlabs.com")
    password = env_value(values, "FTP_PASSWORD")
    if not password:
        password = getpass.getpass(f"FTP password for {username}: ")

    local_dir = ROOT / (args.local_dir or env_value(values, "FTP_LOCAL_DIR", "."))
    if not local_dir.is_dir():
        raise FileNotFoundError(f"Local deploy folder does not exist: {local_dir}")

    excludes = csv(
        env_value(
            values,
            "FTP_EXCLUDE",
            ".git,.git/*,.deploy.env,.deploy.env.example,.DS_Store,__pycache__,*.pyc,*.md,scripts,scripts/*,work,work/*",
        )
    )
    protected_paths = csv(
        env_value(
            values,
            "FTP_PROTECTED_PATHS",
            ".env,.ftpquota,.well-known,.well-known/*,cgi-bin,cgi-bin/*,logs,logs/*,webstats,webstats/*",
        )
    )

    return Config(
        host=host,
        port=int(args.port or env_value(values, "FTP_PORT", "21")),
        username=username,
        password=password,
        remote_dir=args.remote_dir or env_value(values, "FTP_REMOTE_DIR", "/public_html/yupitech"),
        local_dir=local_dir,
        use_tls=bool_value(env_value(values, "FTP_TLS", "1")),
        timeout=int(env_value(values, "FTP_TIMEOUT", "45")),
        excludes=excludes,
        protected_paths=protected_paths,
    )


def connect(config: Config) -> ftplib.FTP:
    ftp_cls = ftplib.FTP_TLS if config.use_tls else ftplib.FTP
    ftp = ftp_cls(timeout=config.timeout)
    ftp.encoding = "utf-8"
    print(f"Connecting to {config.host}:{config.port} as {config.username}...")
    ftp.connect(config.host, config.port)
    ftp.login(config.username, config.password)
    if isinstance(ftp, ftplib.FTP_TLS):
        ftp.prot_p()
    return ftp


def enter_remote_dir(ftp: ftplib.FTP, remote_dir: str, dry_run: bool = False) -> None:
    if not remote_dir or remote_dir == ".":
        return

    if remote_dir.startswith("/"):
        ftp.cwd("/")

    for part in [p for p in remote_dir.split("/") if p]:
        try:
            ftp.cwd(part)
        except ftplib.error_perm:
            if dry_run:
                print(f"[dry-run] mkdir {part}/")
                return
            ftp.mkd(part)
            ftp.cwd(part)


def matches_any(path: str, patterns: tuple[str, ...]) -> bool:
    normalized = path.strip("/")
    name = posixpath.basename(normalized)
    for pattern in patterns:
        p = pattern.strip("/")
        if fnmatch.fnmatch(normalized, p) or fnmatch.fnmatch(name, p):
            return True
    return False


def is_protected(path: str, patterns: tuple[str, ...]) -> bool:
    normalized = path.strip("/")
    if normalized == ".env" or normalized.endswith("/.env"):
        return True
    for pattern in patterns:
        p = pattern.strip("/")
        if normalized == p or normalized.startswith(p + "/") or fnmatch.fnmatch(normalized, p):
            return True
    return False


def local_tree(local_root: Path, excludes: tuple[str, ...]) -> tuple[list[str], list[str]]:
    dirs: list[str] = []
    files: list[str] = []

    for root, dir_names, file_names in os.walk(local_root):
        root_path = Path(root)
        rel_root = root_path.relative_to(local_root).as_posix()
        rel_root = "" if rel_root == "." else rel_root

        kept_dirs: list[str] = []
        for name in dir_names:
            rel = posixpath.join(rel_root, name) if rel_root else name
            if matches_any(rel, excludes):
                continue
            kept_dirs.append(name)
            dirs.append(rel)
        dir_names[:] = kept_dirs

        for name in file_names:
            rel = posixpath.join(rel_root, name) if rel_root else name
            if matches_any(rel, excludes):
                continue
            files.append(rel)

    dirs.sort(key=lambda p: (p.count("/"), p))
    files.sort()
    return dirs, files


def ensure_remote_dir(ftp: ftplib.FTP, rel_dir: str, dry_run: bool) -> None:
    if not rel_dir:
        return
    start_dir = ftp.pwd()
    current = ""
    for part in rel_dir.split("/"):
        current = posixpath.join(current, part) if current else part
        try:
            ftp.cwd(current)
            ftp.cwd(start_dir)
        except ftplib.error_perm:
            ftp.cwd(start_dir)
            if dry_run:
                print(f"[dry-run] mkdir {current}/")
            else:
                print(f"mkdir {current}/")
                ftp.mkd(current)


def remote_mtime(ftp: ftplib.FTP, rel_file: str) -> float | None:
    try:
        response = ftp.sendcmd(f"MDTM {rel_file}")
    except ftplib.all_errors:
        return None
    if not response.startswith("213 "):
        return None
    stamp = response.split(" ", 1)[1].strip()
    try:
        parsed = dt.datetime.strptime(stamp[:14], "%Y%m%d%H%M%S").replace(tzinfo=dt.timezone.utc)
    except ValueError:
        return None
    return parsed.timestamp()


def remote_size(ftp: ftplib.FTP, rel_file: str) -> int | None:
    try:
        ftp.voidcmd("TYPE I")
        return ftp.size(rel_file)
    except ftplib.all_errors:
        return None


def should_upload(ftp: ftplib.FTP, local_file: Path, rel_file: str, force: bool) -> bool:
    if force:
        return True
    size = remote_size(ftp, rel_file)
    if size is None or size != local_file.stat().st_size:
        return True
    mtime = remote_mtime(ftp, rel_file)
    if mtime is None:
        return True
    return local_file.stat().st_mtime > (mtime + 2)


def upload_files(ftp: ftplib.FTP, config: Config, dirs: list[str], files: list[str], args: argparse.Namespace) -> None:
    for rel_dir in dirs:
        ensure_remote_dir(ftp, rel_dir, args.dry_run)

    uploaded = 0
    skipped = 0
    for rel_file in files:
        local_file = config.local_dir / rel_file
        parent = posixpath.dirname(rel_file)
        ensure_remote_dir(ftp, parent, args.dry_run)

        if not should_upload(ftp, local_file, rel_file, args.force):
            skipped += 1
            continue

        if args.dry_run:
            print(f"[dry-run] upload {rel_file}")
        else:
            print(f"upload {rel_file}")
            with local_file.open("rb") as handle:
                ftp.storbinary(f"STOR {rel_file}", handle)
        uploaded += 1

    print(f"Upload pass complete: {uploaded} uploaded, {skipped} unchanged.")


def list_remote_tree(ftp: ftplib.FTP, rel_dir: str = "") -> tuple[set[str], set[str]]:
    files: set[str] = set()
    dirs: set[str] = set()

    try:
        entries = list(ftp.mlsd(rel_dir or "."))
    except ftplib.all_errors:
        entries = []
        names: list[str] = []
        try:
            ftp.retrlines(f"NLST {rel_dir or '.'}", names.append)
        except ftplib.all_errors:
            return files, dirs
        for name in names:
            base = posixpath.basename(name.rstrip("/"))
            if base in {"", ".", ".."}:
                continue
            child = posixpath.join(rel_dir, base) if rel_dir else base
            try:
                current = ftp.pwd()
                ftp.cwd(child)
                ftp.cwd(current)
                entries.append((base, {"type": "dir"}))
            except ftplib.all_errors:
                entries.append((base, {"type": "file"}))

    for name, facts in entries:
        if name in {".", ".."}:
            continue
        child = posixpath.join(rel_dir, name) if rel_dir else name
        kind = facts.get("type", "")
        if kind == "dir":
            dirs.add(child)
            child_files, child_dirs = list_remote_tree(ftp, child)
            files.update(child_files)
            dirs.update(child_dirs)
        elif kind == "file":
            files.add(child)
    return files, dirs


def prune_remote(
    ftp: ftplib.FTP,
    local_dirs: list[str],
    local_files: list[str],
    protected: tuple[str, ...],
    dry_run: bool,
) -> None:
    remote_files, remote_dirs = list_remote_tree(ftp)
    local_file_set = set(local_files)
    local_dir_set = set(local_dirs)

    deleted_files = 0
    deleted_dirs = 0

    for rel_file in sorted(remote_files - local_file_set):
        if is_protected(rel_file, protected):
            continue
        if dry_run:
            print(f"[dry-run] delete {rel_file}")
        else:
            print(f"delete {rel_file}")
            ftp.delete(rel_file)
        deleted_files += 1

    for rel_dir in sorted(remote_dirs - local_dir_set, key=lambda p: p.count("/"), reverse=True):
        if is_protected(rel_dir, protected):
            continue
        try:
            if dry_run:
                print(f"[dry-run] rmdir {rel_dir}/")
            else:
                print(f"rmdir {rel_dir}/")
                ftp.rmd(rel_dir)
            deleted_dirs += 1
        except ftplib.all_errors as exc:
            print(f"skip non-empty/protected dir {rel_dir}/: {exc}")

    print(f"Prune complete: {deleted_files} files and {deleted_dirs} folders removed.")


def list_root(ftp: ftplib.FTP) -> None:
    print(f"FTP root: {ftp.pwd()}")
    try:
        for name, facts in ftp.mlsd("."):
            kind = facts.get("type", "unknown")
            print(f"{kind:8} {name}")
    except ftplib.all_errors:
        entries: list[str] = []
        ftp.retrlines("NLST", entries.append)
        for entry in entries:
            print(entry)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Deploy YupiTech static files over FTP/FTPS.")
    parser.add_argument("--env-file", default=str(DEFAULT_ENV_FILE), help="Path to deploy env file.")
    parser.add_argument("--host", help="FTP host override.")
    parser.add_argument("--port", help="FTP port override.")
    parser.add_argument("--username", help="FTP username override.")
    parser.add_argument("--remote-dir", help="Remote web-root directory override.")
    parser.add_argument("--local-dir", help="Local deploy directory override.")
    parser.add_argument("--list-root", action="store_true", help="List FTP root and exit without uploading.")
    parser.add_argument("--dry-run", action="store_true", help="Show planned upload/delete actions without changing remote files.")
    parser.add_argument("--force", action="store_true", help="Upload every file even when it appears unchanged.")
    parser.add_argument("--prune", action="store_true", help="Delete remote files not present locally, preserving protected paths.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    config = load_config(args)
    ftp = connect(config)
    try:
        if args.list_root:
            list_root(ftp)
            return 0

        dirs, files = local_tree(config.local_dir, config.excludes)
        print(f"Prepared {len(files)} files from {config.local_dir.relative_to(ROOT)}.")
        enter_remote_dir(ftp, config.remote_dir, args.dry_run)
        print(f"Remote directory: {ftp.pwd()}")
        upload_files(ftp, config, dirs, files, args)
        if args.prune:
            prune_remote(ftp, dirs, files, config.protected_paths, args.dry_run)
    finally:
        try:
            ftp.quit()
        except ftplib.all_errors:
            ftp.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
