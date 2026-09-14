#!/bin/sh
# Run a probe inside a gnucash-dev image with an X display and the stand-in
# Finance::Quote on PERL5LIB. The Xvfb started here ends with the container.
#
#   docker run --rm -e TZ=America/Toronto -e TAG=<tag> -v "$PWD:/workspace" -w /workspace \
#       gnucash-dev:<tag> sh tests/research/run_a_gui_probe_under_xvfb.sh tests/research/<probe>.py
Xvfb :99 -screen 0 1280x1024x24 -nolisten tcp >/tmp/xvfb.log 2>&1 &
export DISPLAY=:99
i=0
while [ ! -e /tmp/.X11-unix/X99 ] && [ "$i" -lt 100 ]; do
    python3 -c 'import time; time.sleep(0.1)'
    i=$((i + 1))
done
HERE=$(cd "$(dirname "$0")" && pwd)
# arch and openSUSE have neither JSON nor JSON::Parse, which finance-quote-wrapper needs
if perl -MJSON::Parse -e1 2>/dev/null; then
    export PERL5LIB="$HERE/fake_finance_quote"
else
    export PERL5LIB="$HERE/fake_finance_quote:$HERE/fake_finance_quote_json"
fi
export LANG=C.UTF-8
exec timeout 300 python3 "$@"
