#!/usr/bin/env bash
# Quick launcher: sync assets and run MaaPiCli
set -e
cd "$(dirname "$0")"
cp assets/interface.json deps/bin/interface.json
exec ./deps/bin/MaaPiCli.exe
