#!/usr/bin/env python3
"""Collect everything the headless runtime needs into a directory.

The final stage of the image is `mwaeckerlin/scratch`: no shell, no package
manager. This helper fills the directory the final stage copies, the way the
`tar cph … $(ldd …)` line of the other images of this family does, for a
runtime too large for one command line:

    collect-runtime.py ROOT [--scan DIR…] [--files PATH…] [--packages PKG…]

--scan      every ELF file below DIR contributes its shared libraries; DIR
            itself is copied by the Dockerfile and not by this helper
--files     files and directories copied as they are, symlinks included
--packages  every file of the installed Debian packages these dpkg glob
            patterns match (gcc-[0-9]*); a pattern that matches nothing fails

The shared libraries of every copied ELF file are collected as well. The
helper refuses a result that contains a shell or an interpreter to pivot with.
"""
import argparse
import os
import re
import shutil
import stat
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor

# What a headless image never contains (image contract of this family).
FORBIDDEN = ("/bin/sh", "/bin/bash", "/bin/dash", "/bin/busybox", "/usr/bin/perl")
LDD_PATH = re.compile(r"(?:=>\s*)?(/[^\s]+)\s+\(0x[0-9a-f]+\)")


class Collector:
    def __init__(self, root, scanned):
        self.root = root
        self.scanned = [os.path.abspath(directory) + "/" for directory in scanned]
        self.done = set()
        self.elves = []

    def target(self, path):
        return self.root + path

    def ensure_directory(self, directory):
        if directory == "/":
            return
        self.ensure_directory(os.path.dirname(directory))
        if os.path.islink(directory):
            self.copy(directory)
        elif not os.path.lexists(self.target(directory)):
            os.mkdir(self.target(directory))
            shutil.copystat(directory, self.target(directory))

    def copy(self, path):
        path = os.path.abspath(path)
        if path in self.done or not os.path.lexists(path):
            return
        self.done.add(path)
        self.ensure_directory(os.path.dirname(path))
        destination = self.target(path)
        if os.path.islink(path):
            if not os.path.lexists(destination):
                os.symlink(os.readlink(path), destination)
            self.copy(os.path.realpath(path))
        elif os.path.isdir(path):
            if not os.path.lexists(destination):
                os.mkdir(destination)
                shutil.copystat(path, destination)
        else:
            shutil.copy2(path, destination)
            if is_elf(path):
                self.elves.append(path)

    def copy_tree(self, path):
        self.copy(path)
        if os.path.isdir(path) and not os.path.islink(path):
            for directory, subdirectories, files in os.walk(path):
                for name in subdirectories + files:
                    self.copy(os.path.join(directory, name))

    def inside_scanned(self, path):
        return any(path.startswith(directory) for directory in self.scanned)

    def libraries(self, elves):
        with ThreadPoolExecutor(max_workers=os.cpu_count() or 4) as pool:
            for dependencies in pool.map(ldd, elves):
                for dependency in dependencies:
                    if not self.inside_scanned(os.path.abspath(dependency)):
                        self.copy(dependency)


def is_elf(path):
    try:
        mode = os.stat(path).st_mode
        if not stat.S_ISREG(mode):
            return False
        with open(path, "rb") as handle:
            return handle.read(4) == b"\x7fELF"
    except OSError:
        return False


def ldd(path):
    result = subprocess.run(["ldd", path], capture_output=True, text=True, check=False)
    return LDD_PATH.findall(result.stdout) if result.returncode == 0 else []


def installed_packages(pattern):
    """The installed packages a dpkg glob pattern matches, such as gcc-[0-9]*."""
    result = subprocess.run(
        ["dpkg-query", "-W", "-f", "${db:Status-Abbrev}\t${Package}\n", pattern],
        capture_output=True, text=True, check=False,
    )
    packages = [
        line.split("\t", 1)[1]
        for line in result.stdout.splitlines()
        if line.startswith("ii")
    ]
    if not packages:
        raise SystemExit(f"collect-runtime: no installed package matches {pattern}")
    return packages


def package_files(package):
    result = subprocess.run(["dpkg", "-L", package], capture_output=True, text=True, check=False)
    if result.returncode != 0:
        raise SystemExit(f"collect-runtime: package {package} is not installed")
    return [line for line in result.stdout.splitlines() if line.startswith("/")]


def scan(directories):
    for top in directories:
        for directory, _, files in os.walk(top):
            for name in files:
                path = os.path.join(directory, name)
                if is_elf(path):
                    yield path


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("root")
    parser.add_argument("--scan", nargs="*", default=[])
    parser.add_argument("--files", nargs="*", default=[])
    parser.add_argument("--packages", nargs="*", default=[])
    options = parser.parse_args()

    root = os.path.abspath(options.root)
    os.makedirs(root, exist_ok=True)
    collector = Collector(root, options.scan)
    for path in options.files:
        collector.copy_tree(path)
    packages = sorted({name for pattern in options.packages for name in installed_packages(pattern)})
    for package in packages:
        for path in package_files(package):
            if os.path.lexists(path) and (os.path.islink(path) or not os.path.isdir(path)):
                collector.copy(path)
    collector.libraries(list(scan(options.scan)))
    # Libraries pull in libraries; repeat until nothing new arrives.
    checked = 0
    while checked < len(collector.elves):
        batch = collector.elves[checked:]
        checked = len(collector.elves)
        collector.libraries(batch)

    present = [path for path in FORBIDDEN if os.path.lexists(root + path) and os.path.exists(root + path)]
    if present:
        raise SystemExit(f"collect-runtime: the runtime would contain {', '.join(present)}")
    print(f"collect-runtime: {len(collector.done)} paths collected into {root}", flush=True)


if __name__ == "__main__":
    sys.exit(main())
