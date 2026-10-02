#!/bin/sh
# Build Hardfought's NetHack 5.0.0 tree (k21971/NetHack50) locally, using
# Hardfought's sysconf verbatim except for filesystem paths.
set -eu
ROOT=$(cd "$(dirname "$0")/.." && pwd)
SRC="$ROOT/build/NetHack50"
PREFIX="$ROOT/nethack"
REV=${NETHACK_REV:-a0b9e59d8ac5347409d8cc1dc19b997ce735f035}

[ -d "$SRC" ] || git clone https://github.com/k21971/NetHack50 "$SRC"
cd "$SRC"
git fetch -q origin "$REV" 2>/dev/null || true
git checkout -q "$REV"

# macOS hints + Hardfought's game-affecting compile flags (from hints/hardfought)
{ cat sys/unix/hints/macOS.500
  grep -E '^NHCFLAGS\+=-D(CONFIG_ERROR_SECURE|PANICLOG_FMT2|FCMASK|EDIT_GETLIN|SCORE_ON_BOTL|DGAMELAUNCH|DUMPLOG|DUMPHTML|USE_GENERAL_ALTAR_COLORS|SELF_RECOVER)' sys/unix/hints/hardfought
} > sys/unix/hints/macOS-hardfought
sh sys/unix/setup.sh sys/unix/hints/macOS-hardfought
make fetch-lua
make PREFIX="$PREFIX" HACKDIR="$PREFIX/lib" WANT_WIN_TTY=1 WANT_DEFAULT=tty all
make PREFIX="$PREFIX" HACKDIR="$PREFIX/lib" WANT_WIN_TTY=1 WANT_DEFAULT=tty install

# Hardfought sysconf, with server paths pointed at the local playground.
sed -e "s;/dgldir/userdata/%N/%n/nethack/dumplog;$PREFIX/dumplog;" \
    -e 's;^WIZARDS=.*;WIZARDS=*;' \
    -e 's;^GDBPATH=.*;#GDBPATH=;' -e 's;^PANICTRACE_GDB=1;PANICTRACE_GDB=0;' \
    -e 's;^GREPPATH=.*;GREPPATH=/usr/bin/grep;' \
    sys/unix/sysconf > "$PREFIX/lib/sysconf"
mkdir -p "$PREFIX/dumplog"
echo "built: $(ls "$PREFIX"/lib/nethack* "$PREFIX"/bin/* 2>/dev/null)"
