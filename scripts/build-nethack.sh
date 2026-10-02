#!/bin/sh
# Build Hardfought's NetHack 5.0.0 tree (k21971/NetHack50) locally.
# Works on macOS and Linux. Skips the broken install target entirely
# and assembles the correct layout from build artifacts.
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

# Build everything but DO NOT run make install (it has the path-doubling bug)
make PREFIX="$PREFIX" HACKDIR="$PREFIX/lib" WANT_WIN_TTY=1 WANT_DEFAULT=tty all
make -C dat all
make -C util recover dlb

# ---------------------------------------------------------------------------
# Assemble the correct layout manually from build artifacts.
# ---------------------------------------------------------------------------

# Remove any previous broken install
rm -rf "$PREFIX"

# Create the expected directory structure
mkdir -p "$PREFIX/lib" "$PREFIX/lib/var" "$PREFIX/lib/var/save" "$PREFIX/lib/var/whereis" "$PREFIX/bin" "$PREFIX/dumplog"

# Copy the binary and utilities
cp -a src/nethack "$PREFIX/lib/nethack"
cp -a util/recover "$PREFIX/lib/recover"

# Copy data files
cp -a dat/nhdat "$PREFIX/lib/nhdat"
cp -a dat/symbols "$PREFIX/lib/symbols"
cp -a license "$PREFIX/lib/license"
cp -a doc/NHdump.css "$PREFIX/lib/NHdump.css" 2>/dev/null || true

# Create the expected bin/ symlink
ln -sf ../lib/nethack "$PREFIX/bin/nethack"

# Create required var/ state files
for f in perm record logfile xlogfile livelog; do
    touch "$PREFIX/lib/var/$f"
    chmod 0600 "$PREFIX/lib/var/$f"
done
chmod 0700 "$PREFIX/lib/var" "$PREFIX/lib/var/save" "$PREFIX/lib/var/whereis"

# Generate sysconf with local paths
sed -e "s;/dgldir/userdata/%N/%n/nethack/dumplog;$PREFIX/dumplog;" \
    -e 's;^WIZARDS=.*;WIZARDS=*;' \
    -e 's;^GDBPATH=.*;#GDBPATH=;' -e 's;^PANICTRACE_GDB=1;PANICTRACE_GDB=0;' \
    -e 's;^GREPPATH=.*;GREPPATH=/usr/bin/grep;' \
    "$SRC/sys/unix/sysconf" > "$PREFIX/lib/sysconf"

echo "built: $PREFIX/bin/nethack -> $PREFIX/lib/nethack"
