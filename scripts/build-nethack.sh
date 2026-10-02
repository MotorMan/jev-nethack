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

# The NetHack50 Makefile has a path-doubling bug in its install target:
# it drops files under $PREFIX/home/$USER/$PREFIX/lib instead of $PREFIX/lib.
# Detect that and move everything to the correct layout.
ACTUAL_LIB=$(find "$PREFIX" -type f -name nethack -exec dirname {} \; | head -1)
if [ -n "$ACTUAL_LIB" ] && [ "$ACTUAL_LIB" != "$PREFIX/lib" ]; then
    mkdir -p "$PREFIX/lib"
    cp -a "$ACTUAL_LIB"/* "$PREFIX/lib/" 2>/dev/null || true
    rm -rf "$(dirname "$ACTUAL_LIB")"
fi

# Ensure the expected layout: binary in bin/, data in lib/, state in lib/var/.
mkdir -p "$PREFIX/bin" "$PREFIX/lib/var" "$PREFIX/lib/var/save" "$PREFIX/lib/var/whereis"
ln -sf ../lib/nethack "$PREFIX/bin/nethack"

# NetHack expects var/ files directly under HACKDIR, not nested.
# Move any stray var/ up if it ended up inside lib/.
if [ -d "$PREFIX/lib/var/var" ]; then
    cp -a "$PREFIX/lib/var/var/." "$PREFIX/lib/var/" 2>/dev/null || true
    rm -rf "$PREFIX/lib/var/var"
fi

# Fix permissions on state files.
chmod 0600 "$PREFIX/lib/var/perm" "$PREFIX/lib/var/record" "$PREFIX/lib/var/logfile" "$PREFIX/lib/var/xlogfile" "$PREFIX/lib/var/livelog" 2>/dev/null || true
chmod 0700 "$PREFIX/lib/var" "$PREFIX/lib/var/save" "$PREFIX/lib/var/whereis"

# Hardfought sysconf, with local paths.
sed -e "s;/dgldir/userdata/%N/%n/nethack/dumplog;$PREFIX/dumplog;" \
    -e 's;^WIZARDS=.*;WIZARDS=*;' \
    -e 's;^GDBPATH=.*;#GDBPATH=;' -e 's;^PANICTRACE_GDB=1;PANICTRACE_GDB=0;' \
    -e 's;^GREPPATH=.*;GREPPATH=/usr/bin/grep;' \
    "$SRC/sys/unix/sysconf" > "$PREFIX/lib/sysconf"
mkdir -p "$PREFIX/dumplog"
echo "built: $(ls "$PREFIX"/lib/nethack* "$PREFIX"/bin/* 2>/dev/null)"
