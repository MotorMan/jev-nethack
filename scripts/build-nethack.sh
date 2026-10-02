#!/bin/sh
# Build Hardfought's NetHack 5.0.0 tree (k21971/NetHack50) locally.
# Works on macOS and Linux. Fixes the known path-doubling install bug.
set -eu
ROOT=$(cd "$(dirname "$0")/.." && pwd)
SRC="$ROOT/build/NetHack50"
PREFIX="$ROOT/nethack"
REV=${NETHACK_REV:-a0b9e59d8ac5347409d8cc1dc19b997ce735f035}

[ -d "$SRC" ] || git clone https://github.com/k21971/NetHack50 "$SRC"
cd "$SRC"
git fetch -q origin "$REV" 2>/dev/null || true
git checkout -q "$REV"

# Pick platform hints + Hardfought's game-affecting compile flags (from hints/hardfought)
case "$(uname -s)" in
  Darwin*) BASE_HINTS="sys/unix/hints/macOS.500" ;;
  *) BASE_HINTS="sys/unix/hints/linux.500" ;;
esac
{ cat "$BASE_HINTS"
  grep -E '^NHCFLAGS\+=-D(CONFIG_ERROR_SECURE|PANICLOG_FMT2|FCMASK|EDIT_GETLIN|SCORE_ON_BOTL|DGAMELAUNCH|DUMPLOG|DUMPHTML|USE_GENERAL_ALTAR_COLORS|SELF_RECOVER)' sys/unix/hints/hardfought
} > sys/unix/hints/local-hardfrequent
sh sys/unix/setup.sh sys/unix/hints/local-hardfrequent
make fetch-lua
make PREFIX="$PREFIX" HACKDIR="$PREFIX/lib" WANT_WIN_TTY=1 WANT_DEFAULT=tty all
make PREFIX="$PREFIX" HACKDIR="$PREFIX/lib" WANT_WIN_TTY=1 WANT_DEFAULT=tty install

# ---------------------------------------------------------------------------
# Fix the path-doubling bug in NetHack50's install target.
#
# The Makefile installs files under $PREFIX/home/$USER/$PREFIX/lib
# instead of $PREFIX/lib. Detect where the binary actually landed
# and flatten everything back to the correct layout.
# ---------------------------------------------------------------------------

# Remove any leftover doubled tree from a previous run
rm -rf "$PREFIX/home" 2>/dev/null || true

# Find the actual nethack binary location after make install
ACTUAL_BIN=$(find "$PREFIX" -name nethack -type f 2>/dev/null | head -1)
if [ -z "$ACTUAL_BIN" ]; then
    echo "error: nethack binary not found after install" >&2
    exit 1
fi
ACTUAL_DIR=$(dirname "$ACTUAL_BIN")

# Copy everything from wherever it landed into $PREFIX/lib/
mkdir -p "$PREFIX/lib"
cp -a "$ACTUAL_DIR"/. "$PREFIX/lib/" 2>/dev/null || true

# Create the expected bin/ layout and symlink the binary
mkdir -p "$PREFIX/bin"
if [ ! -e "$PREFIX/bin/nethack" ]; then
    ln -sf ../lib/nethack "$PREFIX/bin/nethack"
fi

# NetHack expects var/ files directly under HACKDIR. Flatten any
# nested var/ from a previous broken install.
if [ -d "$PREFIX/lib/var/var" ]; then
    cp -a "$PREFIX/lib/var/var/." "$PREFIX/lib/var/" 2>/dev/null || true
    rm -rf "$PREFIX/lib/var/var"
fi

# Fix permissions on state files.
for f in perm record logfile xlogfile livelog; do
    if [ -e "$PREFIX/lib/var/$f" ]; then
        chmod 0600 "$PREFIX/lib/var/$f"
    fi
done
chmod 0700 "$PREFIX/lib/var" "$PREFIX/lib/var/save" "$PREFIX/lib/var/whereis" 2>/dev/null || true

# Hardfought sysconf, with local paths.
sed -e "s;/dgldir/userdata/%N/%n/nethack/dumplog;$PREFIX/dumplog;" \
    -e 's;^WIZARDS=.*;WIZARDS=*;' \
    -e 's;^GDBPATH=.*;#GDBPATH=;' -e 's;^PANICTRACE_GDB=1;PANICTRACE_GDB=0;' \
    -e 's;^GREPPATH=.*;GREPPATH=/usr/bin/grep;' \
    "$SRC/sys/unix/sysconf" > "$PREFIX/lib/sysconf"
mkdir -p "$PREFIX/dumplog"

echo "built: $PREFIX/bin/nethack -> $PREFIX/lib/nethack"
