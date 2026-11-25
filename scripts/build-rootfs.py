#!/usr/bin/env python3
"""Build a minimal loong64 rootfs from a ULoong-style apt repository.

Works without root privileges: package payloads are unpacked with tar rather
than by dpkg, so no maintainer scripts are executed. You must add the small
set of generated configuration files (assets/etc) afterwards.

Usage:
    python3 scripts/build-rootfs.py --workdir ./work
"""
import argparse
import gzip
import os
import re
import subprocess
import sys
import urllib.request
from collections import defaultdict

# A deliberately small base: enough for a shell, apt/dpkg and busybox.
BASE = """base-files base-passwd bash dash debconf debianutils diffutils dpkg
findutils gcc-16-base grep gzip hostname init-system-helpers libc-bin libc6
libcrypt1 libgcc-s1 libstdc++6 libtinfo6 libzstd1 login mawk mount
ncurses-base ncurses-bin passwd perl-base sed sysvinit-utils tar util-linux
zlib1g busybox apt ca-certificates""".split()


def parse_packages(path):
    pkgs = {}
    with open(path, encoding="utf-8", errors="replace") as fh:
        for stanza in fh.read().split("\n\n"):
            rec, field = {}, None
            for line in stanza.splitlines():
                if line.startswith(" "):
                    if field:
                        rec[field] += " " + line.strip()
                    continue
                if ":" not in line:
                    continue
                key, value = line.split(":", 1)
                field = key.strip()
                rec[field] = value.strip()
            if rec.get("Package"):
                pkgs[rec["Package"]] = rec
    return pkgs


def resolve(pkgs, seeds):
    providers = defaultdict(list)
    for name, rec in pkgs.items():
        for p in rec.get("Provides", "").split(","):
            token = p.strip().split()[0] if p.strip() else ""
            if token:
                providers[token].append(name)

    def clean(dep):
        return re.split(r"[<(]", dep.strip(), 1)[0].strip()

    wanted, missing = set(), set()

    def add(name):
        name = clean(name)
        if not name or name in wanted:
            return
        if name in pkgs:
            wanted.add(name)
            rec = pkgs[name]
            for field in ("Depends", "Pre-Depends"):
                for alt in rec.get(field, "").split(","):
                    choices = [clean(x) for x in alt.split("|")]
                    picked = next((c for c in choices if c in pkgs), None)
                    if picked is None:
                        picked = next(
                            (providers[c][0] for c in choices if c in providers), None)
                    if picked:
                        add(picked)
                    else:
                        missing.add("|".join(choices))
            return
        if name in providers:
            add(providers[name][0])
            return
        missing.add(name)

    for seed in seeds:
        add(seed)
    return wanted, missing


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--mirror", default="https://uloong.loongfans.cn/uloong")
    ap.add_argument("--suite", default="resolute")
    ap.add_argument("--component", default="main")
    ap.add_argument("--arch", default="loong64")
    ap.add_argument("--workdir", default="./work")
    ap.add_argument("--extra", default="", help="comma-separated extra packages")
    ap.add_argument("--assets", default="assets/etc",
                    help="directory of generated /etc files to copy in")
    args = ap.parse_args()

    work = os.path.abspath(args.workdir)
    rootfs = os.path.join(work, "rootfs")
    debdir = os.path.join(work, "debs")
    os.makedirs(debdir, exist_ok=True)
    os.makedirs(rootfs, exist_ok=True)

    index_url = (f"{args.mirror}/dists/{args.suite}/{args.component}"
                 f"/binary-{args.arch}/Packages.gz")
    index_path = os.path.join(work, "Packages.gz")
    if not os.path.isfile(index_path):
        print(f"[rootfs] fetching {index_url}", flush=True)
        urllib.request.urlretrieve(index_url, index_path)
    with gzip.open(index_path, "rt", encoding="utf-8", errors="replace") as fh:
        text = fh.read()
    plain = os.path.join(work, "Packages")
    if not os.path.isfile(plain):
        with open(plain, "w", encoding="utf-8") as fh:
            fh.write(text)
    pkgs = parse_packages(plain)

    seeds = BASE + [p for p in args.extra.split(",") if p]
    wanted, missing = resolve(pkgs, seeds)
    print(f"[rootfs] closure: {len(wanted)} packages", flush=True)
    if missing:
        print("[rootfs] unresolved (ignored): " + ", ".join(sorted(missing)[:20]),
              flush=True)

    installed = []
    for name in sorted(wanted):
        rec = pkgs[name]
        rel = rec.get("Filename", "")
        if not rel:
            continue
        deb = os.path.join(debdir, os.path.basename(rel))
        if not os.path.isfile(deb):
            try:
                urllib.request.urlretrieve(f"{args.mirror}/{rel}", deb)
            except Exception as exc:
                print(f"[rootfs] WARN download {name}: {exc}", flush=True)
                continue
        producer = subprocess.Popen(["dpkg-deb", "--fsys-tarfile", deb],
                                    stdout=subprocess.PIPE)
        consumer = subprocess.run(
            ["tar", "-xf", "-", "--no-same-owner", "--skip-old-files",
             "-C", rootfs], stdin=producer.stdout)
        producer.stdout.close()
        producer.wait()
        if consumer.returncode == 0:
            installed.append(name)

    # Generated config files that maintainer scripts would normally create.
    if os.path.isdir(args.assets):
        for entry in os.listdir(args.assets):
            src = os.path.join(args.assets, entry)
            if os.path.isfile(src):
                subprocess.run(["cp", "-f", src, os.path.join(rootfs, "etc", entry)],
                               check=True)

    status = os.path.join(rootfs, "var/lib/dpkg/status")
    os.makedirs(os.path.dirname(status), exist_ok=True)
    with open(status, "w", encoding="utf-8") as fh:
        for name in installed:
            rec = pkgs[name]
            fh.write(
                f"Package: {name}\nStatus: install ok installed\n"
                f"Priority: {rec.get('Priority', 'optional')}\n"
                f"Section: {rec.get('Section', 'misc')}\n"
                f"Architecture: {rec.get('Architecture', args.arch)}\n"
                f"Version: {rec.get('Version', '0')}\n"
                f"Maintainer: ULoong package archive\n"
                f"Description: {rec.get('Description', name).splitlines()[0]}\n\n")

    print(f"[rootfs] done: {len(installed)} packages extracted into {rootfs}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
